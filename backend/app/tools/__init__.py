"""
Agent Tooling and Skill Subsystem.
Automatically loads and registers standard skills.
"""

from app.tools.base import BaseSkill, SkillResult
from app.tools.registry import SkillRegistry, registry
import app.tools.filesystem_skills
import app.tools.email_skills

__all__ = ["BaseSkill", "SkillResult", "SkillRegistry", "registry"]
