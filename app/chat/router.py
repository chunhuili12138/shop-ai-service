"""
统一聊天路由
提供统一的聊天接口和会话管理
"""

import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List

from app.common.auth import verify_token, parse_authorization
from app.chat.stream_handler import StreamHandler
from app.rag.session import get_session_manager

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

@router.get("/stream")
async def chat_stream_get(
    message: str,
    session_id: Optional[str] = None,
    image_url: Optional[str] = None,
    token: Optional[str] = None,
    shop_id: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """
    统一聊天接口（GET方式，用于SSE连接）

    EventSource 只支持 GET 请求，所以需要 GET 方式
    Token 通过 URL 参数传递（EventSource 不支持自定义 Header）
    """
    try:
        # 1. 获取 Token（优先从 URL 参数，其次从 Header）
        auth_token = token
        shop_id_int = int(shop_id) if shop_id else None
        
        if not auth_token and authorization:
            auth_token, shop_id_int = parse_authorization(authorization)
        
        if not auth_token:
            raise HTTPException(status_code=401, detail="缺少认证信息")
        
        # 2. 验证 Token
        user_context = await verify_token(auth_token, shop_id_int)

        # 3. 创建流式处理器（传入 session_id 以获取历史消息）
        handler = StreamHandler(user_context, session_id=session_id)

        # 4. 返回 SSE 流
        return StreamingResponse(
            handler.process(message, image_url),
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
        raise HTTPException(status_code=500, detail=f"聊天失败: {str(e)}")


@router.post("/stream")
async def chat_stream_post(
    request: ChatRequest,
    authorization: str = Header(...)
):
    """
    统一聊天接口（POST方式，用于文件上传）

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
        raise HTTPException(status_code=500, detail=f"聊天失败: {str(e)}")


@router.post("/confirm")
async def confirm_action(
    request: ConfirmRequest,
    authorization: str = Header(...)
):
    """
    确认操作接口

    用于执行需要确认的操作（如核销、入库、退款审批等）
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

        # 3. 添加操作人ID
        params = request.params.copy()
        params["operator_id"] = user_context.user_id

        # 4. 执行操作
        result = execute_func(**params)

        return {"success": True, "message": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"操作失败: {str(e)}")


# ==================== 会话管理接口 ====================

@router.get("/sessions")
async def get_sessions(authorization: str = Header(...)):
    """
    获取会话列表
    """
    try:
        # 验证 Token
        token, shop_id = parse_authorization(authorization)
        print(f"[ChatRouter] 获取会话列表 - token: {token[:10]}..., shop_id: {shop_id}")
        
        user_context = await verify_token(token, shop_id)
        print(f"[ChatRouter] Token 验证成功 - user_id: {user_context.user_id}, role: {user_context.role}")

        # 获取会话列表
        session_mgr = get_session_manager()
        sessions = session_mgr.get_user_sessions(user_context.user_id)
        print(f"[ChatRouter] 获取会话列表成功 - count: {len(sessions)}")

        return sessions

    except HTTPException as e:
        print(f"[ChatRouter] HTTP 异常 - status: {e.status_code}, detail: {e.detail}")
        raise
    except Exception as e:
        print(f"[ChatRouter] 未知异常 - error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")


@router.post("/sessions")
async def create_session(
    request: CreateSessionRequest,
    authorization: str = Header(...)
):
    """
    创建新会话
    """
    try:
        # 验证 Token
        token, shop_id = parse_authorization(authorization)
        print(f"[ChatRouter] 创建会话 - token: {token[:10]}..., shop_id: {shop_id}")
        
        user_context = await verify_token(token, shop_id)
        print(f"[ChatRouter] Token 验证成功 - user_id: {user_context.user_id}, role: {user_context.role}")

        # 创建会话
        session_id = str(uuid.uuid4())
        title = request.title or f"会话 {datetime.now().strftime('%m-%d %H:%M')}"

        # 存储会话信息
        session_mgr = get_session_manager()
        session_mgr.create_session(
            session_id=session_id,
            user_id=user_context.user_id,
            title=title,
        )

        print(f"[ChatRouter] 创建会话成功 - session_id: {session_id}, title: {title}")

        return {
            "id": session_id,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": 0,
        }

    except HTTPException as e:
        print(f"[ChatRouter] HTTP 异常 - status: {e.status_code}, detail: {e.detail}")
        raise
    except Exception as e:
        print(f"[ChatRouter] 未知异常 - error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    authorization: str = Header(...)
):
    """
    删除会话
    """
    try:
        # 验证 Token
        token, shop_id = parse_authorization(authorization)
        print(f"[ChatRouter] 删除会话 - session_id: {session_id}, token: {token[:10]}...")
        
        user_context = await verify_token(token, shop_id)
        print(f"[ChatRouter] Token 验证成功 - user_id: {user_context.user_id}")

        # 删除会话
        session_mgr = get_session_manager()
        session_mgr.clear_session(session_id)
        print(f"[ChatRouter] 删除会话成功 - session_id: {session_id}")

        return {"success": True, "message": "会话已删除"}

    except HTTPException as e:
        print(f"[ChatRouter] HTTP 异常 - status: {e.status_code}, detail: {e.detail}")
        raise
    except Exception as e:
        print(f"[ChatRouter] 未知异常 - error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"删除会话失败: {str(e)}")


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    authorization: str = Header(...)
):
    """
    获取会话消息历史
    """
    try:
        # 验证 Token
        token, shop_id = parse_authorization(authorization)
        print(f"[ChatRouter] 获取会话消息 - session_id: {session_id}, token: {token[:10]}...")
        
        user_context = await verify_token(token, shop_id)
        print(f"[ChatRouter] Token 验证成功 - user_id: {user_context.user_id}")

        # 获取消息历史
        session_mgr = get_session_manager()
        history = session_mgr.get_history(session_id)
        print(f"[ChatRouter] 获取消息历史成功 - session_id: {session_id}, count: {len(history)}")

        return history

    except HTTPException as e:
        print(f"[ChatRouter] HTTP 异常 - status: {e.status_code}, detail: {e.detail}")
        raise
    except Exception as e:
        print(f"[ChatRouter] 未知异常 - error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取消息历史失败: {str(e)}")
