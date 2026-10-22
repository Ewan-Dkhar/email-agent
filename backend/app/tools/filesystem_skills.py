"""
Filesystem Skills Module.
Provides secure, sandboxed file reading with path-traversal prevention.
"""

from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from app.tools.base import BaseSkill, SkillResult
from app.tools.registry import registry

# Cross-platform workspace anchor located in user home directory
DEFAULT_SAFE_WORKSPACE = Path.home() / "Documents" / "AgentWorkspace"


def get_safe_workspace(custom_workspace: Optional[Path] = None) -> Path:
    """Returns the resolved safe workspace path, ensuring directory exists."""
    workspace = (custom_workspace or DEFAULT_SAFE_WORKSPACE).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


class ReadFileArgs(BaseModel):
    relative_path: str = Field(
        description="Path relative to ~/Documents/AgentWorkspace (e.g. 'syllabus.txt', 'notes/cs101.md')"
    )


class ReadLocalFileSkill(BaseSkill):
    name = "read_local_file"
    description = (
        "Reads text content from a verified file in the user's workspace directory. "
        "Useful for inspecting notes, past assignments, or local records."
    )
    args_schema = ReadFileArgs

    def __init__(self, workspace_path: Optional[Path] = None):
        self.workspace_path = workspace_path

    async def execute(self, relative_path: str) -> SkillResult:
        try:
            workspace = get_safe_workspace(self.workspace_path)
            target_path = (workspace / relative_path).resolve()

            # Security boundary check: prevent directory traversal attacks
            try:
                target_path.relative_to(workspace)
            except ValueError:
                return SkillResult(
                    success=False,
                    error="Security Error: Path traversal outside workspace forbidden."
                )

            if not target_path.exists():
                return SkillResult(
                    success=False,
                    error=f"File not found: {relative_path}"
                )

            if not target_path.is_file():
                return SkillResult(
                    success=False,
                    error=f"Target path is not a file: {relative_path}"
                )

            # Cap file content to 6,000 characters to protect LLM context window
            full_text = target_path.read_text(encoding="utf-8", errors="ignore")
            max_chars = 6000
            is_truncated = len(full_text) > max_chars
            content = full_text[:max_chars]

            return SkillResult(
                success=True,
                data={
                    "relative_path": relative_path,
                    "content": content,
                    "truncated": is_truncated,
                    "character_count": len(content)
                }
            )
        except Exception as e:
            return SkillResult(success=False, error=f"File read error: {str(e)}")


# Register by default
registry.register(ReadLocalFileSkill)
