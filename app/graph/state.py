"""
Agent状态定义
定义Agent在执行过程中的状态结构
"""

from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from operator import add as add_messages


class AgentState(TypedDict):
    """
    Agent状态定义
    
    Attributes:
        messages: 消息历史
        shop_id: 当前店铺ID
        user_id: 当前用户ID
        user_role: 用户角色
        next_step: 下一步操作
        context: 上下文信息（检索结果等）
        tool_results: 工具调用结果
        needs_approval: 是否需要人工审批
        approval_status: 审批状态
        error_message: 错误信息
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    shop_id: int
    user_id: int
    user_role: str
    next_step: str
    context: str
    tool_results: str
    needs_approval: bool
    approval_status: str
    error_message: str


def create_initial_state(
    user_message: str,
    shop_id: int = 1,
    user_id: int = 0,
    user_role: str = "guest",
) -> AgentState:
    """创建初始状态"""
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content=user_message)],
        "shop_id": shop_id,
        "user_id": user_id,
        "user_role": user_role,
        "next_step": "route",
        "context": "",
        "tool_results": "",
        "needs_approval": False,
        "approval_status": "",
        "error_message": "",
    }
