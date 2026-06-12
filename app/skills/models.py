"""
Skills 数据模型
定义 Skill 和 SkillStep 的数据结构
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class SkillStep:
    """
    Skill 步骤
    
    Attributes:
        step: 步骤序号
        agent: 使用的 Agent 类型（nl2sql/tool/llm/rag）
        task: 任务描述
        description: 详细说明
        query: 具体的查询或指令（如 SQL 查询、工具参数等）
        depends_on: 依赖的步骤序号列表
        is_critical: 是否是关键步骤（失败会影响后续）
    """
    step: int
    agent: str
    task: str
    description: str = ""
    query: str = ""
    depends_on: List[int] = field(default_factory=list)
    is_critical: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "step": self.step,
            "agent": self.agent,
            "task": self.task,
            "description": self.description,
            "query": self.query,
            "depends_on": self.depends_on,
            "is_critical": self.is_critical,
        }


@dataclass
class Skill:
    """
    Skill 定义
    
    Attributes:
        id: 唯一标识
        name: 技能名称
        description: 技能描述
        keywords: 匹配关键词列表
        patterns: 匹配模式（正则表达式）
        steps: 执行步骤列表
        priority: 优先级（越高越优先匹配）
        enabled: 是否启用
    """
    id: str
    name: str
    description: str
    keywords: List[str]
    patterns: List[str]
    steps: List[SkillStep]
    priority: int = 0
    enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "keywords": self.keywords,
            "patterns": self.patterns,
            "steps": [step.to_dict() for step in self.steps],
            "priority": self.priority,
            "enabled": self.enabled,
        }
    
    def matches(self, query: str) -> float:
        """
        检查查询是否匹配此 Skill
        
        Args:
            query: 用户查询
        
        Returns:
            匹配分数（0-1），0 表示不匹配
        """
        import re
        
        query_lower = query.lower()
        score = 0.0
        
        # 1. 关键词匹配
        keyword_matches = 0
        for keyword in self.keywords:
            if keyword.lower() in query_lower:
                keyword_matches += 1
        
        if keyword_matches == 0:
            return 0.0
        
        # 关键词匹配分数
        score += (keyword_matches / len(self.keywords)) * 0.6
        
        # 2. 模式匹配
        pattern_matches = 0
        for pattern in self.patterns:
            try:
                if re.search(pattern, query, re.IGNORECASE):
                    pattern_matches += 1
            except re.error:
                pass
        
        if self.patterns:
            score += (pattern_matches / len(self.patterns)) * 0.4
        else:
            # 没有模式时，只用关键词
            score = (keyword_matches / len(self.keywords))
        
        return min(score, 1.0)
