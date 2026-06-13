"""
统一聊天路由
提供统一的聊天接口和会话管理
"""

import uuid
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List

from app.common.auth import verify_token, parse_authorization
from app.chat.stream_handler import StreamHandler
from app.rag.session import get_session_manager
from app.tools.permissions import is_tool_allowed

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== 请求/响应模型 ====================

class ChatRequest(BaseModel):
    """聊天请求"""
    message: str
    session_id: Optional[str] = None
    image_url: Optional[str] = None


class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    title: Optional[str] = None


class SessionResponse(BaseModel):
    """会话响应"""
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class ConfirmRequest(BaseModel):
    """确认操作请求"""
    action: str
    params: dict


# ==================== 聊天接口 ====================

@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    authorization: str = Header(...)
):
    """
    统一聊天接口（POST 方式，支持 SSE 流式响应）

    Token 通过 Authorization Header 传递，安全可靠。
    自动判断任务类型，路由到合适的模块：
    - 知识问答 → RAG
    - 数据查询 → NL2SQL
    - 工具调用 → Tool
    - 复杂任务 → Supervisor
    """
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. 创建流式处理器（传入 session_id 以获取历史消息）
        handler = StreamHandler(user_context, session_id=request.session_id)

        # 3. 返回 SSE 流
        return StreamingResponse(
            handler.process(request.message, request.image_url),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"聊天失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"聊天失败: {str(e)}")


@router.post("/confirm")
async def confirm_action(
    request: ConfirmRequest,
    authorization: str = Header(...)
):
    """
    确认操作接口

    用于执行需要确认的操作（如核销、入库、退款审批等）
    执行前校验用户角色是否有权执行该操作
    """
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 2. 获取执行函数
        from app.tools import EXECUTE_FUNCTIONS
        execute_func = EXECUTE_FUNCTIONS.get(request.action)

        if not execute_func:
            raise HTTPException(status_code=400, detail=f"未知的操作类型: {request.action}")

        # 3. 权限二次校验：检查当前角色是否有权执行该操作
        if not is_tool_allowed(user_context.role, request.action):
            logger.warning(
                f"权限校验失败 - user_id={user_context.user_id}, "
                f"role={user_context.role}, action={request.action}"
            )
            raise HTTPException(status_code=403, detail=f"当前角色无权执行此操作: {request.action}")

        # 4. 添加操作人ID
        params = request.params.copy()
        params["operator_id"] = user_context.user_id

        # 5. 执行操作
        result = execute_func(**params)

        logger.info(
            f"确认操作执行成功 - user_id={user_context.user_id}, "
            f"action={request.action}"
        )
        return {"success": True, "message": result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"操作失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"操作失败: {str(e)}")


# ==================== 会话管理接口 ====================

@router.get("/sessions")
async def get_sessions(authorization: str = Header(...)):
    """获取会话列表"""
    try:
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)
        logger.debug(f"获取会话列表 - user_id={user_context.user_id}")

        session_mgr = get_session_manager()
        sessions = session_mgr.get_user_sessions(user_context.user_id)
        logger.info(f"获取会话列表成功 - user_id={user_context.user_id}, count={len(sessions)}")

        return sessions

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")


@router.post("/sessions")
async def create_session(
    request: CreateSessionRequest,
    authorization: str = Header(...)
):
    """创建新会话"""
    try:
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        session_id = str(uuid.uuid4())
        title = request.title or f"会话 {datetime.now().strftime('%m-%d %H:%M')}"

        session_mgr = get_session_manager()
        session_mgr.create_session(
            session_id=session_id,
            user_id=user_context.user_id,
            title=title,
        )

        logger.info(f"创建会话成功 - session_id={session_id}, user_id={user_context.user_id}")

        return {
            "id": session_id,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建会话失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    authorization: str = Header(...)
):
    """删除会话"""
    try:
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        session_mgr = get_session_manager()
        session_mgr.clear_session(session_id)

        logger.info(f"删除会话成功 - session_id={session_id}, user_id={user_context.user_id}")
        return {"success": True, "message": "会话已删除"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除会话失败: {str(e)}")


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    authorization: str = Header(...)
):
    """获取会话消息历史"""
    try:
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        session_mgr = get_session_manager()
        history = session_mgr.get_history(session_id)

        logger.debug(f"获取消息历史 - session_id={session_id}, count={len(history)}")
        return history

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取消息历史失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取消息历史失败: {str(e)}")
