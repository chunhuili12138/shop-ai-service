"""
LangGraph Agent 测试用例
测试状态图的路由、节点、边
"""

import pytest
import asyncio

# 设置测试环境
import os
os.environ["ENVIRONMENT"] = "test"
os.environ["LLM_API_KEY"] = "test_key"


class TestAgentState:
    """Agent 状态测试"""
    
    def test_agent_state_structure(self):
        """测试 Agent 状态结构"""
        from app.graph.state import AgentState, create_initial_state
        
        state = create_initial_state(
            user_message="今天的营收",
            shop_id=1,
            user_id=1,
            user_role="店长",
        )
        
        assert "messages" in state
        assert "shop_id" in state
        assert "user_id" in state
        assert "user_role" in state
        assert "next_step" in state
        assert "context" in state
        assert "tool_results" in state
        assert "needs_approval" in state
        assert "approval_status" in state
        assert "error_message" in state
    
    def test_create_initial_state(self):
        """测试创建初始状态"""
        from app.graph.state import create_initial_state
        
        state = create_initial_state(
            user_message="你好",
            shop_id=5,
            user_id=1,
            user_role="导玩员",
        )
        
        assert state["shop_id"] == 5
        assert state["user_id"] == 1
        assert state["user_role"] == "导玩员"
        assert state["next_step"] == "route"
        assert len(state["messages"]) == 1


class TestAgentNodes:
    """Agent 节点测试"""
    
    def test_route_node_exists(self):
        """测试路由节点存在"""
        from app.graph.nodes import route_node
        assert callable(route_node)
    
    def test_rag_node_exists(self):
        """测试 RAG 节点存在"""
        from app.graph.nodes import rag_node
        assert callable(rag_node)
    
    def test_nl2sql_node_exists(self):
        """测试 NL2SQL 节点存在"""
        from app.graph.nodes import nl2sql_node
        assert callable(nl2sql_node)
    
    def test_tool_node_exists(self):
        """测试工具节点存在"""
        from app.graph.nodes import tool_node
        assert callable(tool_node)
    
    def test_respond_node_exists(self):
        """测试响应节点存在"""
        from app.graph.nodes import respond_node
        assert callable(respond_node)
    
    def test_error_node_exists(self):
        """测试错误节点存在"""
        from app.graph.nodes import error_node
        assert callable(error_node)


class TestAgentEdges:
    """Agent 边测试"""
    
    def test_should_continue_exists(self):
        """测试 should_continue 存在"""
        from app.graph.edges import should_continue
        assert callable(should_continue)
    
    def test_route_based_on_intent_exists(self):
        """测试 route_based_on_intent 存在"""
        from app.graph.edges import route_based_on_intent
        assert callable(route_based_on_intent)
    
    def test_route_based_on_intent_query(self):
        """测试意图路由 - 查询"""
        from app.graph.edges import route_based_on_intent
        from app.graph.state import create_initial_state
        
        state = create_initial_state("查询今天的营收")
        state["next_step"] = "query"
        
        result = route_based_on_intent(state)
        assert result == "nl2sql"
    
    def test_route_based_on_intent_tool(self):
        """测试意图路由 - 工具"""
        from app.graph.edges import route_based_on_intent
        from app.graph.state import create_initial_state
        
        state = create_initial_state("帮我查库存")
        state["next_step"] = "tool"
        
        result = route_based_on_intent(state)
        assert result == "tool"
    
    def test_route_based_on_intent_knowledge(self):
        """测试意图路由 - 知识库"""
        from app.graph.edges import route_based_on_intent
        from app.graph.state import create_initial_state
        
        state = create_initial_state("什么是周卡")
        state["next_step"] = "knowledge"
        
        result = route_based_on_intent(state)
        assert result == "rag"
    
    def test_route_based_on_intent_chat(self):
        """测试意图路由 - 对话"""
        from app.graph.edges import route_based_on_intent
        from app.graph.state import create_initial_state
        
        state = create_initial_state("你好")
        state["next_step"] = "chat"
        
        result = route_based_on_intent(state)
        assert result == "respond"


class TestAgentGraph:
    """Agent 图测试"""
    
    def test_build_agent_graph(self):
        """测试构建 Agent 图"""
        from app.graph.agent import build_agent_graph
        
        graph = build_agent_graph()
        assert graph is not None
    
    def test_get_agent_graph_singleton(self):
        """测试获取 Agent 图单例"""
        from app.graph.agent import get_agent_graph
        
        # 重置全局实例
        import app.graph.agent as module
        module._agent_graph = None
        
        graph1 = get_agent_graph()
        graph2 = get_agent_graph()
        
        assert graph1 is graph2


class TestLangFuseConfig:
    """LangFuse 配置测试"""
    
    def test_get_langfuse_returns_none_when_disabled(self):
        """测试 LangFuse 未启用时返回 None"""
        from monitoring.langfuse_config import get_langfuse
        
        # 在测试环境中，LANGFUSE_ENABLED 默认为 False
        result = get_langfuse()
        assert result is None
    
    def test_get_langfuse_callback_handler_returns_none_when_disabled(self):
        """测试 LangFuse 回调处理器未启用时返回 None"""
        from monitoring.langfuse_config import get_langfuse_callback_handler
        
        result = get_langfuse_callback_handler()
        assert result is None
    
    def test_create_trace_returns_none_when_disabled(self):
        """测试创建追踪未启用时返回 None"""
        from monitoring.langfuse_config import create_trace
        
        result = create_trace("test_trace")
        assert result is None
    
    def test_flush_when_disabled(self):
        """测试刷新未启用时不报错"""
        from monitoring.langfuse_config import flush
        
        # 不应该抛出异常
        flush()


class TestAuditLog:
    """审计日志测试"""
    
    def test_audit_log_creation(self):
        """测试审计日志创建"""
        from monitoring.audit_log import AuditLog
        
        log = AuditLog(
            trace_id="test_123",
            question="今天的营收",
            shop_id=1,
            user_id=1,
            role="店长",
            start_time="2024-01-01T00:00:00",
        )
        
        assert log.trace_id == "test_123"
        assert log.question == "今天的营收"
        assert log.shop_id == 1
    
    def test_audit_log_to_dict(self):
        """测试审计日志转字典"""
        from monitoring.audit_log import AuditLog
        
        log = AuditLog(
            trace_id="test_123",
            question="今天的营收",
            shop_id=1,
            user_id=1,
            role="店长",
            start_time="2024-01-01T00:00:00",
        )
        
        result = log.to_dict()
        assert "trace_id" in result
        assert "question" in result
        assert "shop_id" in result
    
    def test_audit_log_to_json(self):
        """测试审计日志转JSON"""
        from monitoring.audit_log import AuditLog
        import json
        
        log = AuditLog(
            trace_id="test_123",
            question="今天的营收",
            shop_id=1,
            user_id=1,
            role="店长",
            start_time="2024-01-01T00:00:00",
        )
        
        json_str = log.to_json()
        parsed = json.loads(json_str)
        assert parsed["trace_id"] == "test_123"
    
    def test_get_audit_logger_singleton(self):
        """测试审计日志记录器单例"""
        from monitoring.audit_log import get_audit_logger
        
        # 重置全局实例
        import monitoring.audit_log as module
        module._audit_logger = None
        
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()
        
        assert logger1 is logger2
    
    def test_audit_logger_start_trace(self):
        """测试开始追踪"""
        from monitoring.audit_log import get_audit_logger
        
        # 重置全局实例
        import monitoring.audit_log as module
        module._audit_logger = None
        
        logger = get_audit_logger()
        log = logger.start_trace(
            trace_id="test_trace",
            question="今天的营收",
            shop_id=1,
        )
        
        assert log is not None
        assert log.trace_id == "test_trace"
        assert log.question == "今天的营收"
    
    def test_audit_logger_log_tool_call(self):
        """测试记录工具调用"""
        from monitoring.audit_log import get_audit_logger
        
        # 重置全局实例
        import monitoring.audit_log as module
        module._audit_logger = None
        
        logger = get_audit_logger()
        logger.start_trace(
            trace_id="test_trace",
            question="今天的营收",
            shop_id=1,
        )
        
        logger.log_tool_call(
            tool_name="query_revenue",
            args={"shop_id": 1, "date_range": "today"},
            result="订单数: 10, 总营收: ¥1000.00",
            success=True,
            duration_ms=50.0,
        )
        
        current_log = logger.get_current_log()
        assert len(current_log.tool_calls) == 1
        assert current_log.tool_calls[0].tool_name == "query_revenue"


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
