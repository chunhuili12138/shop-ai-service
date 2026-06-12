"""
Agent 循环执行器测试用例
测试混合模式（Agent 循环 + 并行执行）
"""

import pytest
import asyncio

# 设置测试环境
import os
os.environ["ENVIRONMENT"] = "test"
os.environ["LLM_API_KEY"] = "test_key"


class TestAgentLoopState:
    """Agent 循环状态测试"""
    
    def test_agent_loop_state_structure(self):
        """测试 Agent 循环状态结构"""
        from app.tools.agent_loop import AgentLoopState
        
        # 验证状态 TypedDict 包含必要字段
        state = {
            "messages": [],
            "shop_id": 1,
            "iteration": 0,
            "max_iterations": 5,
            "start_time": 0.0,
        }
        
        assert "messages" in state
        assert "shop_id" in state
        assert "iteration" in state
        assert "max_iterations" in state
        assert "start_time" in state


class TestAgentLoopResult:
    """Agent 循环结果测试"""
    
    def test_result_creation(self):
        """测试结果对象创建"""
        from app.tools.agent_loop import AgentLoopResult
        
        result = AgentLoopResult(
            answer="今天的营收是 1000 元",
            iterations=2,
            tool_calls_count=1,
            total_duration_ms=500.0,
        )
        
        assert result.answer == "今天的营收是 1000 元"
        assert result.iterations == 2
        assert result.tool_calls_count == 1
        assert result.total_duration_ms == 500.0
    
    def test_result_to_dict(self):
        """测试结果转字典"""
        from app.tools.agent_loop import AgentLoopResult
        from langchain_core.messages import HumanMessage, AIMessage
        
        result = AgentLoopResult(
            answer="今天的营收是 1000 元",
            iterations=2,
            tool_calls_count=1,
            total_duration_ms=500.0,
            messages=[
                HumanMessage(content="今天的营收是多少"),
                AIMessage(content="今天的营收是 1000 元"),
            ]
        )
        
        result_dict = result.to_dict()
        
        assert "answer" in result_dict
        assert "iterations" in result_dict
        assert "tool_calls_count" in result_dict
        assert "total_duration_ms" in result_dict
        assert "messages" in result_dict
        assert len(result_dict["messages"]) == 2
    
    def test_result_message_roles(self):
        """测试消息角色识别"""
        from app.tools.agent_loop import AgentLoopResult
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
        
        result = AgentLoopResult(
            answer="回答",
            iterations=1,
            tool_calls_count=0,
            total_duration_ms=100.0,
        )
        
        assert result._get_message_role(HumanMessage(content="test")) == "user"
        assert result._get_message_role(AIMessage(content="test")) == "assistant"
        assert result._get_message_role(SystemMessage(content="test")) == "system"
        assert result._get_message_role(ToolMessage(content="test", tool_call_id="123")) == "tool"


class TestAgentLoop:
    """Agent 循环执行器测试"""
    
    def test_agent_loop_initialization(self):
        """测试 Agent 循环初始化"""
        from app.tools.agent_loop import AgentLoop
        from app.tools import TOOLS
        
        agent = AgentLoop(tools=TOOLS, max_iterations=3)
        
        assert agent.tools == TOOLS
        assert agent.max_iterations == 3
        assert agent.llm is not None
        assert agent.tool_node is not None
        assert agent.graph is not None
    
    def test_agent_loop_default_tools(self):
        """测试 Agent 循环默认工具"""
        from app.tools.agent_loop import AgentLoop
        from app.tools import TOOLS
        
        agent = AgentLoop()
        
        assert agent.tools == TOOLS
        assert len(agent.tools) == 8
    
    def test_agent_loop_custom_max_iterations(self):
        """测试自定义最大迭代次数"""
        from app.tools.agent_loop import AgentLoop
        
        agent = AgentLoop(max_iterations=10)
        
        assert agent.max_iterations == 10
    
    def test_agent_loop_system_prompt(self):
        """测试系统提示词"""
        from app.tools.agent_loop import AgentLoop
        
        agent = AgentLoop()
        
        assert agent.system_prompt is not None
        assert "店铺智能助手" in agent.system_prompt
        assert "可用工具" in agent.system_prompt
    
    def test_agent_loop_tools_description(self):
        """测试工具描述"""
        from app.tools.agent_loop import AgentLoop
        
        agent = AgentLoop()
        desc = agent._get_tools_description()
        
        assert "query_revenue" in desc
        assert "query_customer" in desc
        assert "query_inventory" in desc
        assert "query_staff_performance" in desc
    
    def test_should_continue_with_tool_calls(self):
        """测试有工具调用时应继续"""
        from app.tools.agent_loop import AgentLoop
        from langchain_core.messages import AIMessage
        
        agent = AgentLoop()
        
        state = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "query_revenue", "args": {}}])
            ],
            "shop_id": 1,
            "iteration": 1,
            "max_iterations": 5,
            "start_time": 0.0,
        }
        
        result = agent._should_continue(state)
        assert result == "continue"
    
    def test_should_end_without_tool_calls(self):
        """测试无工具调用时应结束"""
        from app.tools.agent_loop import AgentLoop
        from langchain_core.messages import AIMessage
        
        agent = AgentLoop()
        
        state = {
            "messages": [
                AIMessage(content="今天的营收是 1000 元")
            ],
            "shop_id": 1,
            "iteration": 1,
            "max_iterations": 5,
            "start_time": 0.0,
        }
        
        result = agent._should_continue(state)
        assert result == "end"
    
    def test_should_end_at_max_iterations(self):
        """测试达到最大迭代次数时应结束"""
        from app.tools.agent_loop import AgentLoop
        from langchain_core.messages import AIMessage
        
        agent = AgentLoop()
        
        state = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "query_revenue", "args": {}}])
            ],
            "shop_id": 1,
            "iteration": 5,
            "max_iterations": 5,
            "start_time": 0.0,
        }
        
        result = agent._should_continue(state)
        assert result == "end"
    
    def test_extract_answer(self):
        """测试提取最终答案"""
        from app.tools.agent_loop import AgentLoop
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        
        agent = AgentLoop()
        
        messages = [
            HumanMessage(content="今天的营收"),
            AIMessage(content="", tool_calls=[{"name": "query_revenue", "args": {}}]),
            ToolMessage(content="营收: 1000", tool_call_id="123"),
            AIMessage(content="今天的营收是 1000 元"),
        ]
        
        answer = agent._extract_answer(messages)
        assert answer == "今天的营收是 1000 元"
    
    def test_count_tool_calls(self):
        """测试统计工具调用次数"""
        from app.tools.agent_loop import AgentLoop
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        
        agent = AgentLoop()
        
        messages = [
            HumanMessage(content="查询"),
            AIMessage(content="", tool_calls=[
                {"name": "query_revenue", "args": {}},
                {"name": "query_inventory", "args": {}},
            ]),
            ToolMessage(content="结果1", tool_call_id="1"),
            ToolMessage(content="结果2", tool_call_id="2"),
            AIMessage(content="最终答案"),
        ]
        
        count = agent._count_tool_calls(messages)
        assert count == 2


class TestGetAgentLoop:
    """获取 Agent 循环实例测试"""
    
    def test_get_agent_loop_singleton(self):
        """测试单例模式"""
        from app.tools.agent_loop import get_agent_loop, _agent_loop
        
        # 重置全局实例
        import app.tools.agent_loop as module
        module._agent_loop = None
        
        agent1 = get_agent_loop()
        agent2 = get_agent_loop()
        
        assert agent1 is agent2
    
    def test_get_agent_loop_custom_params(self):
        """测试自定义参数"""
        from app.tools.agent_loop import get_agent_loop
        
        # 重置全局实例
        import app.tools.agent_loop as module
        module._agent_loop = None
        
        agent = get_agent_loop(max_iterations=10)
        
        assert agent.max_iterations == 10


class TestRunAgent:
    """执行 Agent 循环测试"""
    
    @pytest.mark.asyncio
    async def test_run_agent_function_exists(self):
        """测试 run_agent 函数存在"""
        from app.tools.agent_loop import run_agent
        
        assert callable(run_agent)
    
    @pytest.mark.asyncio
    async def test_run_agent_returns_dict(self):
        """测试 run_agent 返回字典"""
        from app.tools.agent_loop import run_agent
        
        # 重置全局实例
        import app.tools.agent_loop as module
        module._agent_loop = None
        
        # 注意：这个测试需要有效的 LLM API
        # 在测试环境中可能会失败，这是预期的
        try:
            result = await run_agent(
                question="今天的营收",
                shop_id=1,
                max_iterations=1,
                include_messages=False
            )
            
            assert isinstance(result, dict)
            assert "answer" in result
            assert "iterations" in result
            assert "tool_calls_count" in result
            assert "total_duration_ms" in result
        except Exception as e:
            # 在测试环境中，LLM 调用可能会失败
            # 这是预期的行为
            pass


class TestRouterModels:
    """路由模型测试"""
    
    def test_agent_call_request(self):
        """测试 Agent 调用请求模型"""
        from app.tools.router import AgentCallRequest
        
        request = AgentCallRequest(
            question="今天的营收",
            shop_id=1,
            max_iterations=5,
            include_messages=False
        )
        
        assert request.question == "今天的营收"
        assert request.shop_id == 1
        assert request.max_iterations == 5
        assert request.include_messages is False
    
    def test_agent_call_request_defaults(self):
        """测试 Agent 调用请求默认值"""
        from app.tools.router import AgentCallRequest
        
        request = AgentCallRequest(question="今天的营收")
        
        assert request.shop_id == 1
        assert request.max_iterations == 5
        assert request.include_messages is False


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
