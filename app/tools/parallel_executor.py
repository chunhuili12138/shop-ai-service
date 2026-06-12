"""
并行工具调用引擎
支持同时执行多个工具，提高查询效率
"""

import asyncio
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from app.llm import get_chat_llm
from app.tools import TOOLS, TOOL_MAP


@dataclass
class ToolCall:
    """工具调用请求"""
    name: str
    args: Dict[str, Any]
    shop_id: int


@dataclass
class ToolResult:
    """工具执行结果"""
    tool_name: str
    success: bool
    result: Any
    error: Optional[str] = None
    duration_ms: float = 0


@dataclass
class ParallelExecutionResult:
    """并行执行结果"""
    results: List[ToolResult]
    total_duration_ms: float
    success_count: int
    failure_count: int
    
    @property
    def has_results(self) -> bool:
        return self.success_count > 0
    
    def get_successful_results(self) -> List[ToolResult]:
        return [r for r in self.results if r.success]
    
    def get_failed_results(self) -> List[ToolResult]:
        return [r for r in self.results if not r.success]
    
    def to_dict(self) -> Dict:
        return {
            "total_duration_ms": self.total_duration_ms,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "results": [
                {
                    "tool_name": r.tool_name,
                    "success": r.success,
                    "result": r.result if r.success else None,
                    "error": r.error,
                    "duration_ms": r.duration_ms
                }
                for r in self.results
            ]
        }


@dataclass
class ExecutionPlan:
    """执行计划"""
    question: str
    shop_id: int
    tool_calls: List[ToolCall]
    reasoning: str  # LLM 的推理过程


class ParallelToolExecutor:
    """并行工具执行器"""
    
    # 规划提示词
    PLANNING_PROMPT = """你是一个数据分析助手，负责根据用户问题规划需要调用的工具。

## 可用工具
{tools_description}

## 用户问题
{question}

## 店铺ID
{shop_id}

## 要求
1. 分析用户问题，确定需要查询哪些数据
2. 如果问题需要多个维度的数据，可以规划多个工具调用
3. 每个工具调用都要指定 shop_id
4. 返回 JSON 格式的执行计划

## 输出格式
```json
{{
    "reasoning": "分析用户问题的推理过程",
    "tool_calls": [
        {{
            "tool_name": "工具名称",
            "args": {{"shop_id": 1, "其他参数": "值"}}
        }}
    ]
}}
```

请直接返回 JSON，不要包含其他内容："""
    
    def __init__(self):
        self.tools_map = TOOL_MAP
    
    def _get_tools_description(self) -> str:
        """获取工具描述"""
        descriptions = []
        for tool in TOOLS:
            desc = f"- {tool.name}: {tool.description}"
            if hasattr(tool, 'args_schema') and tool.args_schema:
                schema = tool.args_schema.schema()
                if 'properties' in schema:
                    params = list(schema['properties'].keys())
                    desc += f" (参数: {', '.join(params)})"
            descriptions.append(desc)
        return "\n".join(descriptions)
    
    async def plan_execution(
        self,
        question: str,
        shop_id: int
    ) -> ExecutionPlan:
        """
        使用 LLM 规划执行计划
        
        Args:
            question: 用户问题
            shop_id: 店铺 ID
        
        Returns:
            执行计划
        """
        llm = get_chat_llm(temperature=0)
        
        tools_desc = self._get_tools_description()
        
        prompt = self.PLANNING_PROMPT.format(
            tools_description=tools_desc,
            question=question,
            shop_id=shop_id
        )
        
        response = await llm.ainvoke([
            SystemMessage(content="你是一个数据分析规划助手，负责分析用户问题并规划工具调用。"),
            HumanMessage(content=prompt)
        ])
        
        # 解析 JSON 响应
        import json
        try:
            # 提取 JSON 部分
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            plan_data = json.loads(content)
            
            # 构建工具调用列表
            tool_calls = []
            for tc in plan_data.get("tool_calls", []):
                tool_name = tc.get("tool_name")
                args = tc.get("args", {})
                
                # 确保 shop_id 存在
                if "shop_id" not in args:
                    args["shop_id"] = shop_id
                
                if tool_name in self.tools_map:
                    tool_calls.append(ToolCall(
                        name=tool_name,
                        args=args,
                        shop_id=shop_id
                    ))
            
            return ExecutionPlan(
                question=question,
                shop_id=shop_id,
                tool_calls=tool_calls,
                reasoning=plan_data.get("reasoning", "")
            )
        
        except Exception as e:
            # 解析失败，使用默认计划
            return self._default_plan(question, shop_id)
    
    def _default_plan(self, question: str, shop_id: int) -> ExecutionPlan:
        """生成默认执行计划（单工具调用）"""
        # 简单的关键词匹配
        question_lower = question.lower()
        
        tool_name = None
        args = {"shop_id": shop_id}
        
        if any(kw in question_lower for kw in ["营收", "收入", "营业额", "销售"]):
            tool_name = "query_revenue"
            if "月" in question_lower:
                args["date_range"] = "month"
            elif "周" in question_lower:
                args["date_range"] = "week"
            else:
                args["date_range"] = "today"
        
        elif any(kw in question_lower for kw in ["套餐", "热销", "排行"]):
            tool_name = "query_top_packages"
        
        elif any(kw in question_lower for kw in ["顾客", "客户", "会员"]):
            tool_name = "query_customer"
            args["keyword"] = ""  # 查询所有
        
        elif any(kw in question_lower for kw in ["库存", "物料"]):
            tool_name = "query_inventory"
            if "预警" in question_lower or "不足" in question_lower:
                tool_name = "query_low_stock"
        
        elif any(kw in question_lower for kw in ["员工", "绩效", "核销"]):
            tool_name = "query_staff_performance"
        
        # 默认查询营收
        if not tool_name:
            tool_name = "query_revenue"
            args["date_range"] = "today"
        
        return ExecutionPlan(
            question=question,
            shop_id=shop_id,
            tool_calls=[ToolCall(name=tool_name, args=args, shop_id=shop_id)],
            reasoning=f"根据关键词匹配，选择调用 {tool_name}"
        )
    
    async def _execute_single_tool(
        self,
        tool_call: ToolCall
    ) -> ToolResult:
        """
        执行单个工具
        
        Args:
            tool_call: 工具调用请求
        
        Returns:
            工具执行结果
        """
        start_time = time.time()
        
        tool = self.tools_map.get(tool_call.name)
        if not tool:
            return ToolResult(
                tool_name=tool_call.name,
                success=False,
                result=None,
                error=f"工具不存在: {tool_call.name}",
                duration_ms=0
            )
        
        try:
            result = tool.invoke(tool_call.args)
            duration_ms = (time.time() - start_time) * 1000
            
            return ToolResult(
                tool_name=tool_call.name,
                success=True,
                result=result,
                duration_ms=duration_ms
            )
        
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            return ToolResult(
                tool_name=tool_call.name,
                success=False,
                result=None,
                error=str(e),
                duration_ms=duration_ms
            )
    
    async def execute_parallel(
        self,
        tool_calls: List[ToolCall]
    ) -> ParallelExecutionResult:
        """
        并行执行多个工具调用
        
        Args:
            tool_calls: 工具调用列表
        
        Returns:
            并行执行结果
        """
        start_time = time.time()
        
        # 并行执行所有工具
        tasks = [self._execute_single_tool(tc) for tc in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        tool_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                tool_results.append(ToolResult(
                    tool_name=tool_calls[i].name,
                    success=False,
                    result=None,
                    error=str(result)
                ))
            else:
                tool_results.append(result)
        
        total_duration_ms = (time.time() - start_time) * 1000
        
        success_count = sum(1 for r in tool_results if r.success)
        failure_count = len(tool_results) - success_count
        
        return ParallelExecutionResult(
            results=tool_results,
            total_duration_ms=total_duration_ms,
            success_count=success_count,
            failure_count=failure_count
        )
    
    async def execute_with_plan(
        self,
        question: str,
        shop_id: int,
        use_llm_planning: bool = True
    ) -> ParallelExecutionResult:
        """
        规划并执行工具调用
        
        Args:
            question: 用户问题
            shop_id: 店铺 ID
            use_llm_planning: 是否使用 LLM 规划（False 则使用默认规划）
        
        Returns:
            并行执行结果
        """
        # 1. 生成执行计划
        if use_llm_planning:
            plan = await self.plan_execution(question, shop_id)
        else:
            plan = self._default_plan(question, shop_id)
        
        # 2. 并行执行
        if not plan.tool_calls:
            return ParallelExecutionResult(
                results=[],
                total_duration_ms=0,
                success_count=0,
                failure_count=0
            )
        
        return await self.execute_parallel(plan.tool_calls)
    
    async def execute_multiple_questions(
        self,
        questions: List[Dict[str, Any]]
    ) -> List[ParallelExecutionResult]:
        """
        并行执行多个问题的查询
        
        Args:
            questions: 问题列表，每个元素包含 question 和 shop_id
        
        Returns:
            执行结果列表
        """
        tasks = [
            self.execute_with_plan(q["question"], q["shop_id"], use_llm_planning=False)
            for q in questions
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)


# 全局实例
parallel_executor = ParallelToolExecutor()


async def execute_tools_parallel(
    question: str,
    shop_id: int,
    use_llm_planning: bool = True
) -> Dict:
    """
    并行执行工具（API 接口）
    
    Args:
        question: 用户问题
        shop_id: 店铺 ID
        use_llm_planning: 是否使用 LLM 规划
    
    Returns:
        执行结果字典
    """
    result = await parallel_executor.execute_with_plan(
        question, shop_id, use_llm_planning
    )
    return result.to_dict()


async def execute_custom_parallel(
    tool_calls: List[Dict[str, Any]]
) -> Dict:
    """
    自定义并行执行（API 接口）
    
    Args:
        tool_calls: 工具调用列表，每个元素包含 name, args
    
    Returns:
        执行结果字典
    """
    calls = [
        ToolCall(name=tc["name"], args=tc["args"], shop_id=tc["args"].get("shop_id", 1))
        for tc in tool_calls
    ]
    result = await parallel_executor.execute_parallel(calls)
    return result.to_dict()
