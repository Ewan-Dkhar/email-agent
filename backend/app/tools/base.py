"""
Base Skill Specification and Data Contracts.
Defines the standard abstract interface for all agent capabilities.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel, Field


class SkillResult(BaseModel):
    """
    Standardized result contract for all skill executions.
    Guarantees errors are wrapped as observations rather than unhandled exceptions.
    """
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


class BaseSkill(ABC):
    """
    Abstract Base Class for modular agent skills.
    Translates declarative Pydantic schemas into OpenAI/Ollama function calling format.
    """
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
