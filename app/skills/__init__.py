"""
Skills 模块
预设任务执行步骤，提高常见问题的处理成功率
"""

from app.skills.manager import SkillManager, get_skill_manager
from app.skills.models import Skill, SkillStep

__all__ = [
    "SkillManager",
    "get_skill_manager",
    "Skill",
    "SkillStep",
]
