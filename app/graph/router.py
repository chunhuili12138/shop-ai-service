"""
LangGraph模块路由
提供Agent对话API
所有接口需要 Token 验证
"""

import time
import asyncio
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from app.graph.agent import get_agent_graph
from app.graph.state import create_initial_state
from app.common.auth import verify_token, parse_authorization
from monitoring.langfuse_config import create_trace, create_span

router = APIRouter()


class AgentRequest(BaseModel):
    """Agent请求"""
    message: str
    thread_id: str = None  # 用于多轮对话


class AgentResponse(BaseModel):
    """Agent响应"""
    answer: str
    next_step: str
    context: str = ""
    tool_results: str = ""


@router.post("/chat", response_model=AgentResponse)
async def agent_chat(
    request: AgentRequest,
    authorization: str = Header(...)
):
    """
    Agent智能对话

    支持：
    - 知识库问答（RAG）
    - 数据查询（NL2SQL）
    - 工具调用（Tool Calling）
    - 普通对话
    """
    # 创建追踪
    trace = create_trace("agent_chat", {"message": request.message})
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

        # 2. 创建初始状态
        state = create_initial_state(
            user_message=request.message,
            shop_id=user_context.shop_id,
            user_id=user_context.user_id,
            user_role=user_context.role,
        )

        # 3. 获取Agent图并执行
        agent = get_agent_graph()
        # 使用 asyncio.to_thread 包装同步调用，避免阻塞事件循环
        result = await asyncio.to_thread(agent.invoke, state)

        # 4. 提取最终回答
        messages = result.get("messages", [])
        answer = messages[-1].content if messages else "抱歉，无法生成回答"

        # 记录执行结果
        if trace:
            create_span(trace, "agent_result", {
                "answer_length": len(answer),
                "next_step": result.get("next_step", ""),
                "has_context": bool(result.get("context")),
                "has_tool_results": bool(result.get("tool_results")),
                "duration_ms": (time.time() - start_time) * 1000,
            })

        return AgentResponse(
            answer=answer,
            next_step=result.get("next_step", ""),
            context=result.get("context", ""),
            tool_results=result.get("tool_results", ""),
        )

    except HTTPException:
        raise
    except Exception as e:
        if trace:
            create_span(trace, "agent_error", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Agent执行失败: {str(e)}")


@router.post("/chat/stream")
async def agent_chat_stream(
    request: AgentRequest,
    authorization: str = Header(...)
):
    """
    Agent流式对话（SSE）

    返回Server-Sent Events流
    """
    from fastapi.responses import StreamingResponse
    import json

    async def event_generator():
        # 创建追踪
        trace = create_trace("agent_chat_stream", {"message": request.message})
        start_time = time.time()
        
        try:
            # 1. 验证 Token
            token, shop_id = parse_authorization(authorization)
            user_context = await verify_token(token, shop_id)

            # 2. 创建初始状态
            state = create_initial_state(
                user_message=request.message,
                shop_id=user_context.shop_id,
                user_id=user_context.user_id,
                user_role=user_context.role,
            )

            # 3. 获取Agent图并执行
            agent = get_agent_graph()

            # 使用 asyncio.to_thread 包装同步调用，避免阻塞事件循环
            result = await asyncio.to_thread(agent.invoke, state)
            messages = result.get("messages", [])
            answer = messages[-1].content if messages else "抱歉，无法生成回答"

            # 记录执行结果
            if trace:
                create_span(trace, "agent_stream_result", {
                    "answer_length": len(answer),
                    "duration_ms": (time.time() - start_time) * 1000,
                })

            # 模拟流式输出
            chunk_size = 10
            for i in range(0, len(answer), chunk_size):
                chunk = answer[i:i + chunk_size]
                yield f"data: {json.dumps({'content': chunk, 'done': False})}\n\n"

            yield f"data: {json.dumps({'content': '', 'done': True})}\n\n"

        except HTTPException as e:
            if trace:
                create_span(trace, "agent_stream_error", {"error": e.detail})
            yield f"data: {json.dumps({'error': e.detail})}\n\n"
        except Exception as e:
            if trace:
                create_span(trace, "agent_stream_error", {"error": str(e)})
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
