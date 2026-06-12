"""
边定义
定义Agent状态图中的条件边
"""

from app.graph.state import AgentState


def should_continue(state: AgentState) -> str:
    """
    判断是否继续执行
    """
    next_step = state.get("next_step", "")
    error_message = state.get("error_message", "")

    if error_message:
        return "error"
    if next_step in ["respond", "error"]:
        return "end"
    return next_step


def route_based_on_intent(state: AgentState) -> str:
    """
    根据意图路由到不同节点
    """
    next_step = state.get("next_step", "chat")

    routing_map = {
        "query": "nl2sql",
        "tool": "tool",
        "knowledge": "rag",
        "chat": "respond",
    }

    return routing_map.get(next_step, "respond")
