"""
ReAct Agent Harness and Interactive Co-Pilot Loop.
Orchestrates multi-turn reasoning, grammar-constrained tool execution, and SQLite audit logging.
Compatible across all local models (including Gemma-2-9B) using Context-Free Grammar logit masking.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from app.database import get_db
from app.harness.ollama_client import OllamaClient
from app.schemas import CoPilotResponse
from app.tools import SkillRegistry, registry as default_registry

logger = logging.getLogger(__name__)


def build_copilot_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """Builds a grounded system prompt containing tool descriptions and ReAct guidelines."""
    tools_desc = []
    for t in tools:
        fn = t.get("function", {})
        name = fn.get("name", "")
        desc = fn.get("description", "")
        params = fn.get("parameters", {}).get("properties", {})
        param_list = ", ".join(f"{p}: {info.get('type', 'any')}" for p, info in params.items())
        tools_desc.append(f"- {name}({param_list}): {desc}")

    tools_block = "\n".join(tools_desc) if tools_desc else "No external tools available."

    return (
        "You are an autonomous interactive co-pilot assisting the user with completing an academic or administrative task.\n"
        "You reason step-by-step and can call local tools.\n\n"
        "=== AVAILABLE TOOLS ===\n"
        f"{tools_block}\n\n"
        "=== WORKFLOW INSTRUCTIONS ===\n"
        "1. Reason: State your step-by-step reasoning in the 'thought' field.\n"
        "2. Action: If you need to inspect files or draft replies, specify 'action' with the tool 'name' and 'arguments'. Leave 'final_answer' as null.\n"
        "3. Final Answer: If no tool is needed or you have sufficient information to answer the user, set 'action' to null and provide your complete response in 'final_answer'.\n"
        "4. Safety: When drafting an email reply, use 'draft_email_reply'. It stages the email locally for human approval. You NEVER send emails directly.\n"
    )


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
        Executes the ReAct co-pilot loop using grammar-constrained turn decoding
        until the model outputs a final answer or reaches max_iterations.
        """
        tools = self.registry.get_tool_definitions()
        system_prompt = build_copilot_system_prompt(tools)

        user_prompt = (
            f"Active Task: {task_title}\n"
            f"Task Summary: {task_summary}\n\n"
            f"User Instruction: {user_instruction}"
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        actions_taken: List[Dict[str, Any]] = []

        for iteration in range(1, max_iterations + 1):
            logger.info(f"Task {task_id} - ReAct iteration {iteration}/{max_iterations}")

            # 1. Grammar-constrained inference call to local model
            step_result: CoPilotResponse = await self.ollama.step_copilot(
                messages=messages,
                temperature=0.1
            )

            thought = step_result.thought or ""
            action = step_result.action
            final_answer = step_result.final_answer

            # 2. Check if model requested tool execution
            if action and action.name:
                tool_name = action.name
                tool_args = action.arguments or {}

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

                # 5. Append assistant turn and tool observation to context buffer
                messages.append({
                    "role": "assistant",
                    "content": json.dumps(step_result.model_dump())
                })
                messages.append({
                    "role": "user",
                    "content": f"Observation from tool '{tool_name}': {json.dumps(result_dict)}"
                })
            else:
                # 6. Final answer reached
                answer = final_answer or thought
                self._log_execution_step(
                    task_id=task_id,
                    thought=thought,
                    tool_name="final_answer",
                    tool_input={},
                    tool_output={"response": answer},
                    db_path=db_path
                )

                return AgentLoopResult(
                    task_id=task_id,
                    completed=True,
                    final_response=answer,
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
