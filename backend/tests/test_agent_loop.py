"""
Unit Tests for ReAct Agent Loop.
Verifies multi-turn tool execution, SQLite execution audit trails, and circuit breakers.
"""

from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.database import get_db, init_db
from app.harness.agent_loop import ReActAgentHarness
from app.harness.ollama_client import OllamaClient
from app.schemas import CoPilotResponse, ToolCallAction
from app.tools.base import BaseSkill, SkillResult
from app.tools.registry import SkillRegistry
from pydantic import BaseModel, Field


class LookupArgs(BaseModel):
    item: str = Field(description="Item to lookup")


class MockLookupSkill(BaseSkill):
    name = "lookup_info"
    description = "Looks up student info"
    args_schema = LookupArgs

    async def execute(self, item: str) -> SkillResult:
        return SkillResult(success=True, data={"value": f"Record for {item}"})


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_agent_loop.db"
        init_db(db_path)

        # Pre-seed parent email and task for foreign key constraints
        with get_db(db_path) as conn:
            conn.execute(
                """
                INSERT INTO processed_emails (imap_uid, sender, subject, received_at)
                VALUES ('9001', 'advisor@university.edu', 'Advising Task', '2026-10-22')
                """
            )
            conn.execute(
                """
                INSERT INTO tasks (id, email_uid, title, priority_tier, summary, status)
                VALUES (1, '9001', 'Confirm Course Elective', 'P2_ACTIONABLE', 'Need student id', 'PENDING')
                """
            )
        yield db_path


@pytest.mark.asyncio
async def test_react_loop_multi_turn_success(temp_db):
    registry = SkillRegistry()
    registry.register(MockLookupSkill)

    # Turn 1: Model requests tool call
    turn_1_response = CoPilotResponse(
        thought="Let me look up your student record.",
        action=ToolCallAction(name="lookup_info", arguments={"item": "Student_ID"})
    )

    # Turn 2: Model returns final answer after receiving tool observation
    turn_2_response = CoPilotResponse(
        thought="I found your record.",
        final_answer="I found your record: Record for Student_ID. You are all set!"
    )

    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.step_copilot = AsyncMock(side_effect=[turn_1_response, turn_2_response])

    harness = ReActAgentHarness(ollama_client=mock_ollama, skill_registry=registry)
    result = await harness.execute_task(
        task_id=1,
        task_title="Confirm Course Elective",
        task_summary="Need student id",
        user_instruction="What is my student record?",
        db_path=temp_db
    )

    assert result.completed is True
    assert result.iterations == 2
    assert "Record for Student_ID" in result.final_response
    assert len(result.actions_taken) == 1
    assert result.actions_taken[0]["tool_name"] == "lookup_info"

    # Verify execution_logs were persisted in SQLite
    with get_db(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM execution_logs WHERE task_id = 1 ORDER BY id ASC")
        logs = cursor.fetchall()
        assert len(logs) == 2  # 1 tool call + 1 final answer
        assert logs[0]["tool_name"] == "lookup_info"
        assert logs[1]["tool_name"] == "final_answer"


@pytest.mark.asyncio
async def test_react_loop_max_iterations_circuit_breaker(temp_db):
    registry = SkillRegistry()
    registry.register(MockLookupSkill)

    # Model endlessly loops requesting tool calls
    infinite_tool_response = CoPilotResponse(
        thought="Checking again...",
        action=ToolCallAction(name="lookup_info", arguments={"item": "loop"})
    )

    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.step_copilot = AsyncMock(return_value=infinite_tool_response)

    harness = ReActAgentHarness(ollama_client=mock_ollama, skill_registry=registry)
    result = await harness.execute_task(
        task_id=1,
        task_title="Confirm Course Elective",
        task_summary="Need student id",
        user_instruction="Loop forever",
        db_path=temp_db,
        max_iterations=3
    )

    assert result.completed is False
    assert result.iterations == 3
    assert "maximum execution steps reached" in result.final_response.lower()
