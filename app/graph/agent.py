"""
Agent图构建
使用LangGraph构建完整的Agent状态图
"""

from langgraph.graph import StateGraph, END
from app.graph.state import AgentState
from app.graph.nodes import (
    route_node,
    rag_node,
    nl2sql_node,
    tool_node,
    respond_node,
    error_node,
)
from app.graph.edges import should_continue, route_based_on_intent


def build_agent_graph() -> StateGraph:
    """
    构建Agent状态图
    
    图结构：
    start -> route -> [rag | nl2sql | tool | respond] -> respond -> end
                     \-> error -> end
    """
    # 创建状态图
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("route", route_node)
    workflow.add_node("rag", rag_node)
    workflow.add_node("nl2sql", nl2sql_node)
    workflow.add_node("tool", tool_node)
    workflow.add_node("respond", respond_node)
    workflow.add_node("error", error_node)

    # 设置入口点
    workflow.set_entry_point("route")

    # 添加条件边
    workflow.add_conditional_edges(
        "route",
        route_based_on_intent,
        {
            "rag": "rag",
            "nl2sql": "nl2sql",
            "tool": "tool",
            "respond": "respond",
        },
    )

    # 添加普通边
    workflow.add_edge("rag", "respond")
    workflow.add_edge("nl2sql", "respond")
    workflow.add_edge("tool", "respond")
    workflow.add_edge("respond", END)
    workflow.add_edge("error", END)

    # 编译图
    return workflow.compile()


# 全局Agent实例
_agent_graph = None


def get_agent_graph():
    """获取Agent图实例（单例）"""
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph
