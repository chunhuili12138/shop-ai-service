"""
并行工具调用引擎测试用例
"""

import pytest
import asyncio

# 设置测试环境
import os
os.environ["ENVIRONMENT"] = "test"
os.environ["LLM_API_KEY"] = "test_key"


class TestParallelExecutor:
    """并行执行器测试"""
    
    def test_tool_call_creation(self):
        """测试工具调用对象创建"""
        from app.tools.parallel_executor import ToolCall
        
        tc = ToolCall(
            name="query_revenue",
            args={"shop_id": 1, "date_range": "today"},
            shop_id=1
        )
        
        assert tc.name == "query_revenue"
        assert tc.args["shop_id"] == 1
        assert tc.args["date_range"] == "today"
    
    def test_tool_result_creation(self):
        """测试工具结果对象创建"""
        from app.tools.parallel_executor import ToolResult
        
        result = ToolResult(
            tool_name="query_revenue",
            success=True,
            result="订单数: 10, 总营收: ¥1000.00",
            duration_ms=50.5
        )
        
        assert result.tool_name == "query_revenue"
        assert result.success is True
        assert result.duration_ms == 50.5
    
    def test_parallel_execution_result(self):
        """测试并行执行结果"""
        from app.tools.parallel_executor import ParallelExecutionResult, ToolResult
        
        results = [
            ToolResult(tool_name="query_revenue", success=True, result="结果1"),
            ToolResult(tool_name="query_inventory", success=True, result="结果2"),
            ToolResult(tool_name="query_staff", success=False, result=None, error="错误"),
        ]
        
        perf_result = ParallelExecutionResult(
            results=results,
            total_duration_ms=100.0,
            success_count=2,
            failure_count=1
        )
        
        assert perf_result.has_results is True
        assert len(perf_result.get_successful_results()) == 2
        assert len(perf_result.get_failed_results()) == 1
    
    def test_parallel_execution_result_to_dict(self):
        """测试并行执行结果转字典"""
        from app.tools.parallel_executor import ParallelExecutionResult, ToolResult
        
        results = [
            ToolResult(tool_name="query_revenue", success=True, result="结果1", duration_ms=50),
        ]
        
        perf_result = ParallelExecutionResult(
            results=results,
            total_duration_ms=50.0,
            success_count=1,
            failure_count=0
        )
        
        result_dict = perf_result.to_dict()
        
        assert "total_duration_ms" in result_dict
        assert "success_count" in result_dict
        assert "failure_count" in result_dict
        assert "results" in result_dict
        assert len(result_dict["results"]) == 1
    
    def test_execution_plan_creation(self):
        """测试执行计划创建"""
        from app.tools.parallel_executor import ExecutionPlan, ToolCall
        
        plan = ExecutionPlan(
            question="今天的营收和库存",
            shop_id=1,
            tool_calls=[
                ToolCall(name="query_revenue", args={"shop_id": 1}, shop_id=1),
                ToolCall(name="query_inventory", args={"shop_id": 1}, shop_id=1),
            ],
            reasoning="用户需要查询营收和库存两个维度的数据"
        )
        
        assert plan.question == "今天的营收和库存"
        assert len(plan.tool_calls) == 2
    
    def test_default_plan_revenue(self):
        """测试默认计划 - 营收查询"""
        from app.tools.parallel_executor import parallel_executor
        
        plan = parallel_executor._default_plan("今天营业额是多少", 1)
        
        assert len(plan.tool_calls) == 1
        assert plan.tool_calls[0].name == "query_revenue"
    
    def test_default_plan_inventory(self):
        """测试默认计划 - 库存查询"""
        from app.tools.parallel_executor import parallel_executor
        
        plan = parallel_executor._default_plan("库存不足的物料有哪些", 1)
        
        assert len(plan.tool_calls) == 1
        assert plan.tool_calls[0].name == "query_low_stock"
    
    def test_default_plan_staff(self):
        """测试默认计划 - 员工查询"""
        from app.tools.parallel_executor import parallel_executor
        
        plan = parallel_executor._default_plan("本月员工绩效排名", 1)
        
        assert len(plan.tool_calls) == 1
        assert plan.tool_calls[0].name == "query_staff_performance"
    
    def test_default_plan_packages(self):
        """测试默认计划 - 套餐查询"""
        from app.tools.parallel_executor import parallel_executor
        
        plan = parallel_executor._default_plan("热销套餐排行榜", 1)
        
        assert len(plan.tool_calls) == 1
        assert plan.tool_calls[0].name == "query_top_packages"


class TestToolMap:
    """工具映射测试"""
    
    def test_tool_map_contains_all_tools(self):
        """测试工具映射包含所有工具"""
        from app.tools import TOOL_MAP
        
        expected_tools = [
            "query_revenue",
            "query_top_packages",
            "query_customer",
            "query_customer_purchases",
            "query_inventory",
            "query_low_stock",
            "query_staff_performance",
            "query_staff_list",
        ]
        
        for tool_name in expected_tools:
            assert tool_name in TOOL_MAP, f"工具 {tool_name} 未在 TOOL_MAP 中"
    
    def test_tools_list_not_empty(self):
        """测试工具列表不为空"""
        from app.tools import TOOLS
        
        assert len(TOOLS) > 0
        assert len(TOOLS) == 8  # 当前应有 8 个工具


class TestRouterModels:
    """路由模型测试"""
    
    def test_parallel_call_request(self):
        """测试并行调用请求模型"""
        from app.tools.router import ParallelCallRequest
        
        request = ParallelCallRequest(
            question="今天的营收",
            shop_id=1,
            use_llm_planning=True
        )
        
        assert request.question == "今天的营收"
        assert request.shop_id == 1
        assert request.use_llm_planning is True
    
    def test_custom_tool_call(self):
        """测试自定义工具调用模型"""
        from app.tools.router import CustomToolCall
        
        tc = CustomToolCall(
            name="query_revenue",
            args={"shop_id": 1, "date_range": "today"}
        )
        
        assert tc.name == "query_revenue"
        assert tc.args["shop_id"] == 1
    
    def test_custom_parallel_request(self):
        """测试自定义并行请求模型"""
        from app.tools.router import CustomParallelRequest, CustomToolCall
        
        request = CustomParallelRequest(
            tool_calls=[
                CustomToolCall(name="query_revenue", args={"shop_id": 1}),
                CustomToolCall(name="query_inventory", args={"shop_id": 1}),
            ]
        )
        
        assert len(request.tool_calls) == 2


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
