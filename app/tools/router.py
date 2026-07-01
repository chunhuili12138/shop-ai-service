"""
工具路由模块
提供工具调用 API（/api/tools/）
所有接口需要 Token 验证
"""

import time
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional
from langchain_core.messages import HumanMessage
from app.llm import get_chat_llm
from app.tools import TOOLS, TOOL_MAP
from app.tools.parallel_executor import (
    execute_tools_parallel,
    execute_custom_parallel,
    parallel_executor
)
from app.tools.agent_loop import run_agent, run_agent_simple
from app.common.user_context import UserContext
from app.common.auth import verify_token, parse_authorization
from app.common.system_prompts import SECURITY_RULES
from monitoring.langfuse_config import create_trace, create_span

router = APIRouter()


# ==================== Request / Response ====================

class ToolCallRequest(BaseModel):
    """工具调用请求"""
    question: str


class ToolCallResponse(BaseModel):
    """工具调用响应"""
    answer: str
    tool_used: str
    tool_result: str


class ParallelCallRequest(BaseModel):
    """并行工具调用请求"""
    question: str
    use_llm_planning: bool = True


class CustomToolCall(BaseModel):
    """自定义工具调用"""
    name: str
    args: dict


class CustomParallelRequest(BaseModel):
    """自定义并行调用请求"""
    tool_calls: List[CustomToolCall]


class AgentCallRequest(BaseModel):
    """Agent 循环调用请求"""
    question: str
    max_iterations: int = 5
    include_messages: bool = False


# ==================== Endpoints ====================

@router.post("/call", response_model=ToolCallResponse)
async def call_tool(
    request: ToolCallRequest,
    authorization: str = Header(...)
):
    """
    智能工具调用（单工具）

    流程：
    1. 验证 Token 并获取用户信息
    2. LLM 根据用户问题选择合适的工具（自动获取 Pydantic JSON Schema）
    3. LLM 输出结构化参数
    4. 执行工具并返回结果
    """
    # 创建追踪
    trace = create_trace("tool_call", {"question": request.question})
    start_time = time.time()
    
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. 获取角色可用的工具
        from app.tools.permissions import get_tools_for_role
        available_tools = get_tools_for_role(user_context.role)

        # 3. 调用LLM进行工具选择
        llm = get_chat_llm(temperature=0).bind_tools(available_tools)
        security_prompt = f"\n\n{SECURITY_RULES}"
        response = await llm.ainvoke([
            HumanMessage(content=f"店铺ID: {user_context.shop_id}\n\n用户问题: {request.question}{security_prompt}")
        ])

        # 4. 检查是否有工具调用
        if response.tool_calls:
            tool_call = response.tool_calls[0]
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            # 确保shop_id参数存在
            if "shop_id" not in tool_args:
                tool_args["shop_id"] = user_context.shop_id

            # 从注册表中获取工具
            tool = TOOL_MAP.get(tool_name)
            if tool:
                # 记录工具选择
                if trace:
                    create_span(trace, "tool_selection", {
                        "tool_name": tool_name,
                        "tool_args": str(tool_args)[:200],
                    })
                
                tool_result = tool.invoke(tool_args)
                
                # 记录工具执行结果
                if trace:
                    create_span(trace, "tool_execution", {
                        "tool_name": tool_name,
                        "result_length": len(tool_result) if tool_result else 0,
                        "duration_ms": (time.time() - start_time) * 1000,
                    })
                
                return ToolCallResponse(
                    answer=f"根据查询结果：\n{tool_result}",
                    tool_used=tool_name,
                    tool_result=tool_result,
                )

        # 记录未使用工具
        if trace:
            create_span(trace, "no_tool_used", {
                "response_length": len(response.content) if response.content else 0,
                "duration_ms": (time.time() - start_time) * 1000,
            })

        return ToolCallResponse(
            answer=response.content,
            tool_used="none",
            tool_result="",
        )

    except HTTPException:
        raise
    except Exception as e:
        if trace:
            create_span(trace, "tool_call_error", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"工具调用失败: {str(e)}")


@router.post("/parallel")
async def parallel_call(
    request: ParallelCallRequest,
    authorization: str = Header(...)
):
    """
    并行工具调用

    支持：
    1. 验证 Token 并获取用户信息
    2. LLM 智能规划多个工具调用
    3. 并行执行所有工具
    4. 合并返回结果

    示例问题：
    - "帮我查一下今天的营收和库存预警情况"
    - "本月员工绩效排名和热销套餐"
    """
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. 执行并行调用
        result = await execute_tools_parallel(
            question=request.question,
            shop_id=user_context.shop_id,
            use_llm_planning=request.use_llm_planning,
            user_role=user_context.role
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"并行调用失败: {str(e)}")


@router.post("/custom-parallel")
async def custom_parallel_call(
    request: CustomParallelRequest,
    authorization: str = Header(...)
):
    """
    自定义并行调用

    用户直接指定要调用的工具和参数，系统并行执行。

    示例：
    {
        "tool_calls": [
            {"name": "query_revenue", "args": {"shop_id": 1, "date_range": "today"}},
            {"name": "query_low_stock", "args": {"shop_id": 1}},
            {"name": "query_staff_performance", "args": {"shop_id": 1}}
        ]
    }
    """
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. 检查权限
        from app.tools.permissions import is_tool_allowed
        for tc in request.tool_calls:
            if not is_tool_allowed(user_context.role, tc.name):
                raise HTTPException(status_code=403, detail=f"无权使用工具: {tc.name}")

        # 3. 执行并行调用
        tool_calls = [
            {"name": tc.name, "args": tc.args}
            for tc in request.tool_calls
        ]
        result = await execute_custom_parallel(tool_calls)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"自定义并行调用失败: {str(e)}")


@router.post("/plan")
async def plan_execution(
    request: ToolCallRequest,
    authorization: str = Header(...)
):
    """
    生成执行计划（不执行）

    用于调试和查看 LLM 的规划结果
    """
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. 生成计划
        plan = await parallel_executor.plan_execution(
            question=request.question,
            shop_id=user_context.shop_id
        )
        return {
            "question": plan.question,
            "shop_id": plan.shop_id,
            "reasoning": plan.reasoning,
            "tool_calls": [
                {
                    "name": tc.name,
                    "args": tc.args
                }
                for tc in plan.tool_calls
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"规划失败: {str(e)}")


@router.post("/agent")
async def agent_call(
    request: AgentCallRequest,
    authorization: str = Header(...)
):
    """
    Agent 循环调用（混合模式）

    实现 Agent 循环 + 并行执行的混合模式：
    1. 验证 Token 并获取用户信息
    2. LLM 动态决策需要调用哪些工具
    3. 如果本轮有多个 tool_calls，自动并行执行
    4. 汇总 Observation，继续下一轮决策
    5. 直到 LLM 决定不再调用工具，生成最终答案

    支持权限隔离：
    - 根据用户角色过滤可用工具
    - 根据角色动态生成系统提示词
    - 根据问题复杂度动态选择模型

    示例问题：
    - "帮我分析一下本月营收趋势和库存预警"（店长）
    - "查询顾客张三的信息"（导玩员）
    - "查看库存预警"（仓管）
    """
    # 创建追踪
    trace = create_trace("agent_loop", {"question": request.question})
    start_time = time.time()
    
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 记录用户信息
        if trace:
            create_span(trace, "user_context", {
                "user_id": user_context.user_id,
                "shop_id": user_context.shop_id,
                "role": user_context.role,
            })

        # 2. 执行 Agent
        result = await run_agent(
            question=request.question,
            user_context=user_context,
            max_iterations=request.max_iterations,
            include_messages=request.include_messages
        )
        
        # 记录执行结果
        if trace:
            create_span(trace, "agent_result", {
                "iterations": result.get("iterations", 0),
                "tool_calls_count": result.get("tool_calls_count", 0),
                "model_used": result.get("model_used", ""),
                "answer_length": len(result.get("answer", "")),
                "duration_ms": (time.time() - start_time) * 1000,
            })
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        if trace:
            create_span(trace, "agent_error", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Agent 调用失败: {str(e)}")


@router.get("/list")
async def list_tools(
    role: Optional[str] = None,
    authorization: str = Header(...)
):
    """
    列出可用工具及其 JSON Schema

    Args:
        role: 角色名称（可选，不传则返回所有工具）
    """
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. 获取工具列表
        from app.tools.permissions import get_tools_for_role, get_all_roles, get_role_description

        if role:
            tools = get_tools_for_role(role)
        else:
            tools = get_tools_for_role(user_context.role)

        return {
            "role": role or user_context.role,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "schema": t.args_schema.schema() if hasattr(t, "args_schema") and t.args_schema else None,
                }
                for t in tools
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {str(e)}")


@router.get("/roles")
async def list_roles(authorization: str = Header(...)):
    """列出所有角色及其权限"""
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. 获取角色列表
        from app.tools.permissions import (
            get_all_roles,
            get_role_description,
            get_allowed_tool_names,
        )

        roles = get_all_roles()
        return {
            "roles": [
                {
                    "name": role,
                    "description": get_role_description(role),
                    "allowed_tools": get_allowed_tool_names(role),
                }
                for role in roles
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取角色列表失败: {str(e)}")
