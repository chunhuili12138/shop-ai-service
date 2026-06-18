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


# ==================== 辅助函数 ====================

def query_operated_record_details(action: str, params: dict, shop_id: int) -> dict:
    """
    根据操作类型查询被操作记录的关键信息

    Args:
        action: 操作类型（如 refund_reject, game_session_checkin 等）
        params: 操作参数（包含各种 ID）
        shop_id: 店铺 ID

    Returns:
        查询到的详情字典，查询失败返回空字典
    """
    from app.nl2sql.executor import execute_sql

    try:
        if "refund" in action:
            refund_id = params.get("refund_id")
            if refund_id:
                results = execute_sql(
                    "SELECT rr.id, c.nickname, p.name as package_name, rr.refund_amount "
                    "FROM refund_records rr "
                    "JOIN purchases pu ON rr.purchase_id = pu.id "
                    "JOIN packages p ON pu.package_id = p.id "
                    "LEFT JOIN customers c ON pu.customer_id = c.id "
                    "WHERE rr.id = :id AND pu.shop_id = :sid",
                    {"id": refund_id, "sid": shop_id}
                )
                return results[0] if results else {}

        elif "checkin" in action:
            cs_id = params.get("customer_session_id")
            if cs_id:
                results = execute_sql(
                    "SELECT cs.id, c.nickname, p.name as package_name "
                    "FROM customer_sessions cs "
                    "JOIN purchases pu ON cs.purchase_id = pu.id "
                    "JOIN packages p ON pu.package_id = p.id "
                    "LEFT JOIN customers c ON pu.customer_id = c.id "
                    "WHERE cs.id = :id AND cs.shop_id = :sid",
                    {"id": cs_id, "sid": shop_id}
                )
                return results[0] if results else {}

        elif "finish" in action:
            gs_id = params.get("game_session_id")
            if gs_id:
                results = execute_sql(
                    "SELECT gs.id, c.nickname, p.name as package_name "
                    "FROM game_sessions gs "
                    "LEFT JOIN customer_sessions cs ON gs.customer_session_id = cs.id "
                    "LEFT JOIN purchases pu ON cs.purchase_id = pu.id "
                    "JOIN packages p ON pu.package_id = p.id "
                    "LEFT JOIN customers c ON pu.customer_id = c.id "
                    "WHERE gs.id = :id AND gs.shop_id = :sid",
                    {"id": gs_id, "sid": shop_id}
                )
                return results[0] if results else {}

        elif "material_inbound" in action or "material_outbound" in action:
            material_id = params.get("material_id")
            if material_id:
                results = execute_sql(
                    "SELECT id, name, unit FROM materials WHERE id = :id AND shop_id = :sid",
                    {"id": material_id, "sid": shop_id}
                )
                return results[0] if results else {}

        elif "grant_coupon" in action:
            coupon_id = params.get("coupon_id")
            if coupon_id:
                results = execute_sql(
                    "SELECT id, name, value FROM coupons WHERE id = :id AND shop_id = :sid",
                    {"id": coupon_id, "sid": shop_id}
                )
                return results[0] if results else {}

        elif "reply_feedback" in action:
            feedback_id = params.get("feedback_id")
            if feedback_id:
                results = execute_sql(
                    "SELECT f.id, c.nickname "
                    "FROM feedbacks f "
                    "LEFT JOIN customers c ON f.customer_id = c.id "
                    "WHERE f.id = :id AND f.shop_id = :sid",
                    {"id": feedback_id, "sid": shop_id}
                )
                return results[0] if results else {}

        elif "send_notification" in action:
            return {"title": params.get("title", ""), "content": params.get("content", "")}

    except Exception as e:
        logger.warning(f"[QueryDetails] 查询操作详情失败: {str(e)}")

    return {}


def build_operation_result_text(action: str, result: str, details: dict) -> str:
    """
    构建完整的操作结果文本

    Args:
        action: 操作类型
        result: 执行结果消息
        details: 查询到的详情

    Returns:
        完整的结果文本
    """
    from app.tools import TOOL_DISPLAY_NAMES

    display_name = TOOL_DISPLAY_NAMES.get(action, action)

    if not details:
        return f"{display_name}：{result}"

    desc_parts = []

    if "refund" in action:
        name = details.get("nickname", "")
        pkg = details.get("package_name", "")
        amount = details.get("refund_amount")
        if name:
            desc_parts.append(name)
        if pkg:
            desc_parts.append(pkg)
        if amount:
            desc_parts.append(f"¥{amount}")
    elif "checkin" in action or "finish" in action:
        name = details.get("nickname", "")
        pkg = details.get("package_name", "")
        if name:
            desc_parts.append(name)
        if pkg:
            desc_parts.append(pkg)
    elif "material" in action:
        name = details.get("name", "")
        unit = details.get("unit", "")
        if name:
            desc_parts.append(name)
        if unit:
            desc_parts.append(unit)
    elif "coupon" in action:
        name = details.get("name", "")
        value = details.get("value")
        if name:
            desc_parts.append(name)
        if value:
            desc_parts.append(f"¥{value}")
    elif "feedback" in action:
        name = details.get("nickname", "")
        if name:
            desc_parts.append(name)
    elif "notification" in action:
        title = details.get("title", "")
        if title:
            desc_parts.append(title)

    desc = "（".join(desc_parts) + "）" if desc_parts else ""
    return f"{display_name}：{desc} - {result}"


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
    session_id: Optional[str] = None


class SelectRequest(BaseModel):
    """多选确认请求"""
    action: str
    selected_ids: list
    params: dict
    session_id: Optional[str] = None


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

        # 4. 添加操作人ID 和 token（用于代理调用 Java 后端 API）
        params = request.params.copy()
        params["operator_id"] = user_context.user_id
        params["token"] = token

        # 5. 执行操作
        logger.info(f"[Confirm] 执行 {request.action}, params={params}")
        result = execute_func(**params)
        logger.info(f"[Confirm] {request.action} 返回: {result}")

        # 6. 查询被操作记录详情，构建完整结果文本
        details = query_operated_record_details(request.action, params, shop_id)
        summary = build_operation_result_text(request.action, str(result), details)

        # 7. 保存执行结果到会话（持久化，重新打开面板时可反显）
        if request.session_id:
            try:
                from app.rag.session import get_session_manager
                session_mgr = get_session_manager()
                session_mgr.add_message(request.session_id, "assistant", summary)
            except Exception as e:
                logger.warning(f"保存确认结果消息失败: {str(e)}")

        logger.info(
            f"确认操作执行成功 - user_id={user_context.user_id}, "
            f"action={request.action}"
        )
        return {"success": True, "message": summary}

    except HTTPException as e:
        # 保存错误消息到会话
        if request.session_id:
            try:
                from app.rag.session import get_session_manager
                session_mgr = get_session_manager()
                session_mgr.add_message(request.session_id, "assistant", f"操作失败: {e.detail}")
            except Exception:
                pass
        raise
    except Exception as e:
        logger.error(f"操作失败: {str(e)}", exc_info=True)
        # 保存错误消息到会话
        if request.session_id:
            try:
                from app.rag.session import get_session_manager
                session_mgr = get_session_manager()
                session_mgr.add_message(request.session_id, "assistant", f"操作失败: {str(e)}")
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"操作失败: {str(e)}")


@router.post("/select")
async def select_action(
    request: SelectRequest,
    authorization: str = Header(...)
):
    """
    多选确认接口

    用于处理多条记录的批量操作（如批量拒绝退款）
    """
    try:
        # 1. 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 1.5 校验 selected_ids
        if not request.selected_ids or len(request.selected_ids) == 0:
            raise HTTPException(status_code=400, detail="请选择至少一条记录")

        # 2. 获取批量执行函数
        batch_action = f"{request.action}_batch"
        from app.tools import EXECUTE_FUNCTIONS
        execute_func = EXECUTE_FUNCTIONS.get(batch_action)

        if not execute_func:
            # 没有批量函数，逐个执行
            results = []
            single_func = EXECUTE_FUNCTIONS.get(request.action)
            if not single_func:
                raise HTTPException(status_code=400, detail=f"未知的操作类型: {request.action}")

            # 根据 action 确定 ID 参数名
            if "refund" in request.action:
                id_param = "refund_id"
            elif "checkin" in request.action:
                id_param = "customer_session_id"
            elif "finish" in request.action:
                id_param = "game_session_id"
            else:
                id_param = "id"

            for item_id in request.selected_ids:
                params = request.params.copy()
                params[id_param] = item_id
                params["operator_id"] = user_context.user_id
                params["token"] = token
                params["shop_id"] = shop_id

                # 核销需要 customer_id，从数据库查询
                if "checkin" in request.action and "customer_id" not in params:
                    from app.nl2sql.executor import execute_sql
                    cs = execute_sql(
                        "SELECT pu.customer_id FROM customer_sessions cs "
                        "JOIN purchases pu ON cs.purchase_id = pu.id "
                        "WHERE cs.id = :id AND cs.shop_id = :sid",
                        {"id": item_id, "sid": shop_id}
                    )
                    if cs:
                        params["customer_id"] = cs[0]["customer_id"]

                try:
                    logger.info(f"[Select] 执行 {request.action} item_id={item_id}, params={params}")
                    result = single_func(**params)
                    logger.info(f"[Select] {request.action} item_id={item_id} 返回: {result}")
                    results.append({"id": item_id, "success": True, "message": result})
                except Exception as e:
                    logger.error(f"[Select] {request.action} item_id={item_id} 异常: {str(e)}")
                    results.append({"id": item_id, "success": False, "message": str(e)})

            success_count = sum(1 for r in results if r["success"])

            # 构建详细结果文本（每条查询详情）
            from app.tools import TOOL_DISPLAY_NAMES
            display_name = TOOL_DISPLAY_NAMES.get(request.action, request.action)
            detail_lines = [f"{display_name}操作完成："]
            for r in results:
                # 查询该条记录的详情
                item_params = {id_param: r["id"], "shop_id": shop_id}
                details = query_operated_record_details(request.action, item_params, shop_id)
                detail_text = build_operation_result_text(request.action, r.get("message", ""), details)
                # 只取冒号后面的部分作为单条结果
                if "：" in detail_text:
                    detail_text = detail_text.split("：", 1)[1]
                detail_lines.append(f"- {detail_text}")

            detail_lines.append(f"\n成功 {success_count}/{len(request.selected_ids)} 条")
            summary = "\n".join(detail_lines)
        else:
            # 有批量函数
            params = request.params.copy()
            # 根据 action 确定批量 ID 参数名
            if "refund" in request.action:
                batch_param = "refund_ids"
            elif "checkin" in request.action:
                batch_param = "customer_session_ids"
            elif "finish" in request.action:
                batch_param = "game_session_ids"
            else:
                batch_param = "ids"
            params[batch_param] = request.selected_ids
            params["operator_id"] = user_context.user_id
            params["token"] = token
            params["shop_id"] = shop_id
            result = execute_func(**params)
            summary = str(result)

        # 保存结果到会话
        if request.session_id:
            try:
                from app.rag.session import get_session_manager
                session_mgr = get_session_manager()
                session_mgr.add_message(request.session_id, "assistant", summary)
            except Exception as e:
                logger.warning(f"保存多选结果消息失败: {str(e)}")

        logger.info(f"多选操作执行成功 - user_id={user_context.user_id}, action={request.action}, count={len(request.selected_ids)}")
        return {"success": True, "message": summary}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"多选操作失败: {str(e)}", exc_info=True)
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
