"""
Agent 间通信协议
定义 Agent 消息和结果的数据结构
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class AgentType(str, Enum):
    """Agent 类型枚举"""
    RAG = "rag"
    NL2SQL = "nl2sql"
    TOOL = "tool"
    VISION = "vision"
    LLM = "llm"           # 新增：LLM 总结分析
    SUPERVISOR = "supervisor"


class MessageType(str, Enum):
    """消息类型枚举"""
    TASK = "task"          # 任务分配
    RESULT = "result"      # 结果返回
    QUERY = "query"        # 查询请求
    ERROR = "error"        # 错误信息


class TaskComplexity(str, Enum):
    """任务复杂度枚举"""
    SIMPLE = "simple"      # 简单任务（单 Agent）
    COMPLEX = "complex"    # 复杂任务（多 Agent 协作）


@dataclass
class AgentMessage:
    """
    Agent 间消息
    用于 Agent 之间的通信
    """
    sender: str                    # 发送者（Agent 类型）
    receiver: str                  # 接收者（Agent 类型）
    content: Any                   # 消息内容
    message_type: str              # 消息类型
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "message_type": self.message_type,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class AgentResult:
    """
    Agent 执行结果
    用于返回 Agent 执行结果
    """
    agent: str                     # Agent 类型
    result: Any                    # 执行结果
    confidence: float = 1.0        # 置信度
    duration_ms: float = 0         # 执行耗时（毫秒）
    success: bool = True           # 是否成功
    error: Optional[str] = None    # 错误信息
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "agent": self.agent,
            "result": self.result,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class SubTask:
    """
    子任务
    复杂任务拆分后的子任务
    """
    id: int                              # 子任务 ID
    task: str                            # 子任务描述
    agent: str                           # 执行的 Agent 类型
    description: str = ""                # 任务说明
    query: str = ""                      # 预定义查询（Skill 使用）
    depends_on: List[int] = field(default_factory=list)  # 依赖的子任务 ID 列表
    result: Optional[AgentResult] = None  # 执行结果
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "task": self.task,
            "agent": self.agent,
            "description": self.description,
            "query": self.query,
            "depends_on": self.depends_on,
            "result": self.result.to_dict() if self.result else None,
        }


@dataclass
class TaskPlan:
    """
    任务执行计划
    Supervisor 分析任务后生成的执行计划
    """
    task: str                              # 原始任务
    complexity: str                        # 任务复杂度
    agents: List[str]                      # 需要调用的 Agent 列表
    parallel: bool = False                 # 是否并行执行
    reasoning: str = ""                    # 判断原因
    dependencies: Dict[str, List[str]] = field(default_factory=dict)  # Agent 依赖关系
    sub_tasks: List[SubTask] = field(default_factory=list)  # 子任务列表
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task": self.task,
            "complexity": self.complexity,
            "agents": self.agents,
            "parallel": self.parallel,
            "reasoning": self.reasoning,
            "dependencies": self.dependencies,
            "sub_tasks": [sub_task.to_dict() for sub_task in self.sub_tasks],
        }


@dataclass
class MultiAgentState:
    """
    多 Agent 执行状态
    用于跟踪多 Agent 协作的执行状态
    """
    task: str                              # 原始任务
    user_id: int                           # 用户 ID
    shop_id: int                           # 店铺 ID
    role: str                              # 用户角色
    plan: Optional[TaskPlan] = None        # 执行计划
    results: List[AgentResult] = field(default_factory=list)  # 执行结果列表
    final_answer: Optional[str] = None     # 最终答案
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    
    def add_result(self, result: AgentResult):
        """添加执行结果"""
        self.results.append(result)
    
    def get_result(self, agent_type: str) -> Optional[AgentResult]:
        """获取指定 Agent 的执行结果"""
        for result in self.results:
            if result.agent == agent_type:
                return result
        return None
    
    def is_complete(self) -> bool:
        """检查是否所有 Agent 都执行完成"""
        if not self.plan:
            return False
        completed_agents = {r.agent for r in self.results if r.success}
        required_agents = set(self.plan.agents)
        return required_agents.issubset(completed_agents)
    
    def get_duration_ms(self) -> float:
        """获取总执行时间"""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return (datetime.now() - self.start_time).total_seconds() * 1000
