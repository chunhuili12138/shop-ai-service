"""
多 Agent 协作模块
实现 Supervisor + 专业化 Agent 架构
"""

from app.multi_agent.protocol import AgentMessage, AgentResult, TaskPlan, SubTask
from app.multi_agent.router import TaskRouter
from app.multi_agent.supervisor import SupervisorAgent
from app.multi_agent.rag_agent import RAGAgent
from app.multi_agent.nl2sql_agent import NL2SQLAgent
from app.multi_agent.tool_agent import ToolAgent
from app.multi_agent.vision_agent import VisionAgent

__all__ = [
    "AgentMessage",
    "AgentResult",
    "TaskPlan",
    "SubTask",
    "TaskRouter",
    "SupervisorAgent",
    "RAGAgent",
    "NL2SQLAgent",
    "ToolAgent",
    "VisionAgent",
]
