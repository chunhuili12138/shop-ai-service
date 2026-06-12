"""
经验池数据模型定义
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class AgentType(str, Enum):
    """Agent 类型枚举"""
    NL2SQL = "nl2sql"
    TOOL = "tool"
    RAG = "rag"
    SUPERVISOR = "supervisor"


class ExperienceType(str, Enum):
    """经验类型枚举"""
    SUCCESS = "success"              # 成功案例
    FAILURE_FIX = "failure_fix"      # 失败 + 修复案例
    FAILURE = "failure"              # 失败案例（无修复）


@dataclass
class Experience:
    """
    经验条目
    
    Attributes:
        id: 唯一标识符
        agent_type: Agent 类型（nl2sql/tool/rag/supervisor）
        experience_type: 经验类型（success/failure_fix/failure）
        question: 用户问题
        solution: 解决方案（SQL/工具调用/回答）
        result_summary: 结果摘要
        error: 错误信息（失败时）
        fixed_solution: 修复后的方案（失败时）
        solving_process: 解决流程（步骤列表）
        metadata: 额外元数据
        created_at: 创建时间
        updated_at: 更新时间
        usage_count: 使用次数
        success_count: 成功次数
        quality_score: 质量评分（0-100）
    """
    id: str
    agent_type: str
    experience_type: str
    question: str
    solution: str
    result_summary: str = ""
    error: str = ""
    fixed_solution: str = ""
    solving_process: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    usage_count: int = 0
    success_count: int = 0
    quality_score: int = 70
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "agent_type": self.agent_type,
            "experience_type": self.experience_type,
            "question": self.question,
            "solution": self.solution,
            "result_summary": self.result_summary,
            "error": self.error,
            "fixed_solution": self.fixed_solution,
            "solving_process": self.solving_process,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "quality_score": self.quality_score,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Experience':
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            agent_type=data.get("agent_type", ""),
            experience_type=data.get("experience_type", ""),
            question=data.get("question", ""),
            solution=data.get("solution", ""),
            result_summary=data.get("result_summary", ""),
            error=data.get("error", ""),
            fixed_solution=data.get("fixed_solution", ""),
            solving_process=data.get("solving_process", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            usage_count=data.get("usage_count", 0),
            success_count=data.get("success_count", 0),
            quality_score=data.get("quality_score", 70),
        )
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count
