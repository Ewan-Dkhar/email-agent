# SKILLS.md - Skill Authoring & Execution Standard

In this architecture, a **Skill** is a modular, self-describing Python class that gives the agent the ability to interact with the local environment (disk, network, shell). 

Skills are never hardcoded into prompts. They inherit from a standardized abstract base class and declare their parameters via Pydantic.

---

## 1. Base Skill Interface (`backend/app/tools/base.py`)

All skills must inherit from `BaseSkill`:

```python
from abc import ABC, abstractmethod
from typing import Type, Dict, Any, Optional
from pydantic import BaseModel

class SkillResult(BaseModel):
    success: bool
    data: Any = None
    error: Optional[str] = None

class BaseSkill(ABC):
    name: str
    description: str
    args_schema: Type[BaseModel]

    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        """
        Executes the skill deterministically.
        Must NEVER raise an uncaught exception; return SkillResult(success=False, error=str(e)).
        """
        pass

    def to_ollama_tool(self) -> Dict[str, Any]:
        """Translates the skill into standard OpenAI/Ollama function calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema.model_json_schema(),
            }
        }
```

---

## 2. Dynamic Skill Registry (`backend/app/tools/registry.py`)

The registry dynamically discovers, tracks, and invokes skills:

```python
from typing import Dict, List, Any
from app.tools.base import BaseSkill, SkillResult

class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill_cls: type[BaseSkill]) -> None:
        instance = skill_cls()
        self._skills[instance.name] = instance

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [skill.to_ollama_tool() for skill in self._skills.values()]

    async def dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> SkillResult:
        if tool_name not in self._skills:
            return SkillResult(
                success=False, 
                error=f"Skill '{tool_name}' not found. Available skills: {list(self._skills.keys())}"
            )
        
        skill = self._skills[tool_name]
        try:
            # Validate parameters through the skill's specific Pydantic schema
            validated_args = skill.args_schema.model_validate(arguments)
            return await skill.execute(**validated_args.model_dump())
        except Exception as e:
            return SkillResult(success=False, error=f"Validation or execution failure: {str(e)}")

# Global Singleton
registry = SkillRegistry()
```

---

## 3. Standard Core Skills

### 3.1 Skill: `draft_email_reply`
Drafts a context-aware email response and saves it as a draft without sending.

```python
from pydantic import BaseModel, Field
from app.tools.base import BaseSkill, SkillResult
from app.tools.registry import registry

class DraftEmailArgs(BaseModel):
    recipient: str = Field(..., description="Target email address")
    subject: str = Field(..., description="Subject line (typically starting with 'Re: ')")
    body_markdown: str = Field(..., description="Content of the reply in Markdown format")

class DraftEmailReplySkill(BaseSkill):
    name = "draft_email_reply"
    description = "Drafts an email reply for user review. Never sends the email directly."
    args_schema = DraftEmailArgs

    async def execute(self, recipient: str, subject: str, body_markdown: str) -> SkillResult:
        try:
            draft_id = f"draft_{hash(recipient + subject)}"
            # Staged in local SQLite drafts table awaiting user approval
            return SkillResult(
                success=True, 
                data={"draft_id": draft_id, "message": "Draft created successfully. Awaiting user review."}
            )
        except Exception as e:
            return SkillResult(success=False, error=str(e))

registry.register(DraftEmailReplySkill)
```

### 3.2 Skill: `read_local_file`
Allows Gemma to inspect local workspace files, student records, or past documents to help fill out forms or answer questions. This implementation uses cross-platform path resolution.

```python
from pydantic import BaseModel, Field
from pathlib import Path
from app.tools.base import BaseSkill, SkillResult
from app.tools.registry import registry

# Cross-platform workspace anchor located in user home directory
SAFE_WORKSPACE = Path.home() / "Documents" / "AgentWorkspace"
SAFE_WORKSPACE.mkdir(parents=True, exist_ok=True)

class ReadFileArgs(BaseModel):
    relative_path: str = Field(..., description="Path relative to ~/Documents/AgentWorkspace")

class ReadLocalFileSkill(BaseSkill):
    name = "read_local_file"
    description = "Reads text content from a verified workspace file or document."
    args_schema = ReadFileArgs

    async def execute(self, relative_path: str) -> SkillResult:
        try:
            target_path = (SAFE_WORKSPACE / relative_path).resolve()
            
            # Security boundary check: prevent directory traversal attacks
            if not str(target_path).startswith(str(SAFE_WORKSPACE.resolve())):
                return SkillResult(success=False, error="Security Error: Path traversal outside workspace forbidden.")

            if not target_path.exists():
                return SkillResult(success=False, error=f"File not found: {relative_path}")

            content = target_path.read_text(encoding="utf-8", errors="ignore")[:6000]
            return SkillResult(success=True, data={"content": content})
        except Exception as e:
            return SkillResult(success=False, error=str(e))

registry.register(ReadLocalFileSkill)
```

---

## 4. How to Add a New Skill (Checklist for AI Agents)
When asked to implement a new capability:
1. Create a new file in `backend/app/tools/` or add to an existing skill module.
2. Define a Pydantic `args_schema` specifying all required parameters with detailed `Field(description=...)` annotations.
3. Inherit from `BaseSkill` and implement the `async execute()` method.
4. Catch all internal exceptions and wrap results in `SkillResult(success=False, error=...)`.
5. Register the skill with `registry.register(YourNewSkill)`.