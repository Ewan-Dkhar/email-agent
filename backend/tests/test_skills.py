"""
Unit Tests for Agent Skills and Registry.
Validates skill schema generation, sandboxed filesystem security, and HITL email drafting.
"""

from pathlib import Path
import tempfile
import pytest
from pydantic import BaseModel, Field
from app.tools.base import BaseSkill, SkillResult
from app.tools.email_skills import DraftEmailReplySkill
from app.tools.filesystem_skills import ReadLocalFileSkill, get_safe_workspace
from app.tools.registry import SkillRegistry


class DummyArgs(BaseModel):
    query: str = Field(description="Search query")


class DummySkill(BaseSkill):
    name = "dummy_skill"
    description = "Test skill for registry verification"
    args_schema = DummyArgs

    async def execute(self, query: str) -> SkillResult:
        return SkillResult(success=True, data=f"Result for: {query}")


@pytest.mark.asyncio
async def test_registry_registration_and_dispatch():
    registry = SkillRegistry()
    registry.register(DummySkill)

    tools = registry.get_tool_definitions()
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "dummy_skill"
    assert "query" in tools[0]["function"]["parameters"]["properties"]

    # Successful dispatch with valid args
    result = await registry.dispatch("dummy_skill", {"query": "hello agent"})
    assert result.success is True
    assert result.data == "Result for: hello agent"

    # Missing argument validation error (handled cleanly, no unhandled exception)
    invalid_result = await registry.dispatch("dummy_skill", {})
    assert invalid_result.success is False
    assert "validation" in invalid_result.error.lower()

    # Unknown tool
    unknown_result = await registry.dispatch("non_existent_tool", {})
    assert unknown_result.success is False
    assert "not found" in unknown_result.error.lower()


@pytest.mark.asyncio
async def test_read_local_file_safe_read_and_traversal_defense():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "AgentWorkspace"
        workspace.mkdir()

        # Create a valid workspace file
        safe_file = workspace / "notes.txt"
        safe_file.write_text("CS101: Midterm on Friday.", encoding="utf-8")

        # Create an outside secret file
        secret_file = Path(tmpdir) / "secret.key"
        secret_file.write_text("SUPER_SECRET_KEY", encoding="utf-8")

        skill = ReadLocalFileSkill(workspace_path=workspace)

        # 1. Valid read within workspace
        res = await skill.execute(relative_path="notes.txt")
        assert res.success is True
        assert res.data["content"] == "CS101: Midterm on Friday."
        assert res.data["truncated"] is False

        # 2. File not found inside workspace
        missing_res = await skill.execute(relative_path="does_not_exist.txt")
        assert missing_res.success is False
        assert "not found" in missing_res.error.lower()

        # 3. Path traversal attack (../secret.key)
        attack_res = await skill.execute(relative_path="../secret.key")
        assert attack_res.success is False
        assert "security error" in attack_res.error.lower()
        assert "path traversal" in attack_res.error.lower()


@pytest.mark.asyncio
async def test_read_local_file_truncation():
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / "AgentWorkspace"
        workspace.mkdir()

        large_file = workspace / "large.txt"
        large_file.write_text("A" * 10000, encoding="utf-8")

        skill = ReadLocalFileSkill(workspace_path=workspace)
        res = await skill.execute(relative_path="large.txt")

        assert res.success is True
        assert len(res.data["content"]) == 6000
        assert res.data["truncated"] is True


@pytest.mark.asyncio
async def test_draft_email_reply_hitl_staging():
    skill = DraftEmailReplySkill()
    res = await skill.execute(
        recipient="prof@university.edu",
        subject="Re: Course Registration",
        body_markdown="Dear Professor, I would like to enroll in Section B."
    )

    assert res.success is True
    draft_id = res.data["draft_id"]
    assert draft_id.startswith("draft_")
    assert "awaiting user approval" in res.data["message"].lower()

    # Verify staged record
    staged = DraftEmailReplySkill.get_staged_draft(draft_id)
    assert staged is not None
    assert staged["recipient"] == "prof@university.edu"
    assert staged["status"] == "PENDING_APPROVAL"
