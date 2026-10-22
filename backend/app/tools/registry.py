"""
Dynamic Skill Registry.
Discovers, tracks, validates, and dispatches agent skills.
"""

import logging
from typing import Any, Dict, List, Optional, Type
from app.tools.base import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill_cls: Type[BaseSkill]) -> None:
        """Instantiates and registers a skill under its unique name."""
        instance = skill_cls()
        self._skills[instance.name] = instance
        logger.info(f"Registered agent skill: {instance.name}")

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Returns tool schema definitions formatted for Ollama / OpenAI function calling."""
        return [skill.to_ollama_tool() for skill in self._skills.values()]

    def get_skill(self, tool_name: str) -> Optional[BaseSkill]:
        """Retrieves a registered skill instance by name."""
        return self._skills.get(tool_name)

    async def dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> SkillResult:
        """
        Dispatches execution to the target skill.
        Validates parameters through the skill's specific Pydantic schema before invocation.
        """
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
            logger.warning(f"Validation or execution failure in '{tool_name}': {str(e)}")
            return SkillResult(
                success=False,
                error=f"Validation or execution failure: {str(e)}"
            )


# Global Singleton Registry
registry = SkillRegistry()
