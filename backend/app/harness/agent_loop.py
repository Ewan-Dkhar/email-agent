"""
ReAct Agent Harness and Interactive Co-Pilot Loop.
Orchestrates multi-turn reasoning, tool execution, and SQLite audit logging.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from app.database import get_db
from app.harness.ollama_client import OllamaClient
from app.tools.registry import SkillRegistry, registry as default_registry

logger = logging.getLogger(__name__)

SYSTEM_CO_PILOT_PROMPT = """You are an autonomous interactive co-pilot assisting the user with completing an academic or administrative task.
You have access to tools that allow you to read local workspace documents and draft context-aware email replies.

=== OPERATIONAL WORKFLOW (ReAct) ===
1. Reason: Consider what information is needed to fulfill the user's instruction.
2. Act: Call a relevant tool to inspect files or draft replies if needed.
3. Observe: Review the tool output and decide if further actions are required.
4. Finish: Once all necessary actions are taken, provide a clear, helpful final answer to the user.

=== SAFETY & HUMAN-IN-THE-LOOP INVARIANTS ===
- When reading local files, only request files within the designated workspace.
- When drafting an email reply, use the draft_email_reply tool. It will stage the email for human approval. You NEVER send emails directly.
- Be concise, direct, and professional.
"""


class AgentLoopResult(BaseModel):
    task_id: int
    completed: bool
    final_response: str
    iterations: int
    actions_taken: List[Dict[str, Any]] = []


class ReActAgentHarness:
    def __init__(
        self,
        ollama_client: Optional[OllamaClient] = None,
        skill_registry: Optional[SkillRegistry] = None
    ):
        self.ollama = ollama_client or OllamaClient()
        self.registry = skill_registry or default_registry

    def _log_execution_step(
        self,
        task_id: int,
        thought: Optional[str],
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Dict[str, Any],
        db_path: Optional[Path] = None
    ) -> None:
        """Appends an execution step to the execution_logs SQLite audit table."""
        with get_db(db_path) as conn:
            conn.execute(
                """
                INSERT INTO execution_logs (task_id, thought, tool_name, tool_input, tool_output)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    thought,
                    tool_name,
                    json.dumps(tool_input),
                    json.dumps(tool_output)
                )
            )

    async def execute_task(
        self,
        task_id: int,
        task_title: str,
        task_summary: str,
        user_instruction: str,
        db_path: Optional[Path] = None,
        max_iterations: int = 6
    ) -> AgentLoopResult:
        """
        Executes the ReAct co-pilot loop until the model outputs a final answer
        or reaches max_iterations.
        """
        user_prompt = (
            f"Active Task: {task_title}\n"
            f"Task Summary: {task_summary}\n\n"
            f"User Instruction: {user_instruction}"
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_CO_PILOT_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        actions_taken: List[Dict[str, Any]] = []
        tools = self.registry.get_tool_definitions()

        for iteration in range(1, max_iterations + 1):
            logger.info(f"Task {task_id} - ReAct iteration {iteration}/{max_iterations}")

            # 1. Inference call to local model
            assistant_message = await self.ollama.chat_completion(
                messages=messages,
                tools=tools if tools else None,
                temperature=0.2
            )

            thought = assistant_message.get("content") or ""
            tool_calls = assistant_message.get("tool_calls")

            # 2. Check if model requested tool execution
            if tool_calls:
                # Append assistant message with tool calls to context history
                messages.append(assistant_message)

                for call in tool_calls:
                    function_data = call.get("function", {})
                    tool_name = function_data.get("name", "")
                    raw_args = function_data.get("arguments", {})

                    if isinstance(raw_args, str):
                        try:
                            tool_args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            tool_args = {"raw": raw_args}
                    else:
                        tool_args = raw_args or {}

                    # 3. Dispatch to skill registry
                    skill_result = await self.registry.dispatch(tool_name, tool_args)
                    result_dict = skill_result.model_dump()

                    # 4. Log to SQLite execution audit trail
                    self._log_execution_step(
                        task_id=task_id,
                        thought=thought,
                        tool_name=tool_name,
                        tool_input=tool_args,
                        tool_output=result_dict,
                        db_path=db_path
                    )

                    actions_taken.append({
                        "iteration": iteration,
                        "thought": thought,
                        "tool_name": tool_name,
                        "input": tool_args,
                        "output": result_dict
                    })

                    # 5. Feed tool observation back to context buffer
                    messages.append({
                        "role": "tool",
                        "content": json.dumps(result_dict)
                    })
            else:
                # 6. Final answer reached (no tool calls emitted)
                self._log_execution_step(
                    task_id=task_id,
                    thought=thought,
                    tool_name="final_answer",
                    tool_input={},
                    tool_output={"response": thought},
                    db_path=db_path
                )

                return AgentLoopResult(
                    task_id=task_id,
                    completed=True,
                    final_response=thought,
                    iterations=iteration,
                    actions_taken=actions_taken
                )

        # Max iterations exceeded without final answer
        return AgentLoopResult(
            task_id=task_id,
            completed=False,
            final_response="Maximum execution steps reached before completing task.",
            iterations=max_iterations,
            actions_taken=actions_taken
        )
