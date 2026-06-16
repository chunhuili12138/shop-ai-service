"""
后端 API 客户端
代理调用 Java 后端接口，复用后端已有的业务逻辑
"""

import httpx
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

JAVA_BACKEND_URL = settings.BACKEND_URL


def call_backend_api_sync(
    method: str,
    path: str,
    token: str,
    shop_id: int,
    params: dict = None,
    timeout: float = 10.0,
) -> dict:
    """
    同步调用 Java 后端 API（用于 execute 函数，同步上下文）

    Args:
        method: HTTP 方法（GET/POST/PUT/DELETE）
        path: API 路径
        token: 用户 token
        shop_id: 店铺 ID
        params: 请求参数
        timeout: 超时时间

    Returns:
        后端响应 {success: bool, msg: str, data: ...}
    """
    if shop_id:
        authorization = f"Bearer-{shop_id}-{token}"
    else:
        authorization = f"Bearer {token}"

    url = f"{JAVA_BACKEND_URL}{path}"

    try:
        with httpx.Client(timeout=timeout) as client:
            if method.upper() == "GET":
                response = client.get(url, params=params, headers={"Authorization": authorization})
            elif method.upper() == "POST":
                response = client.post(url, data=params, headers={"Authorization": authorization})
            elif method.upper() == "PUT":
                response = client.put(url, data=params, headers={"Authorization": authorization})
            elif method.upper() == "DELETE":
                response = client.delete(url, params=params, headers={"Authorization": authorization})
            else:
                return {"success": False, "msg": f"不支持的 HTTP 方法: {method}"}

        data = response.json()
        logger.info(f"[BackendAPI] {method} {path} -> {response.status_code}, success={data.get('success')}")
        return data

    except httpx.TimeoutException:
        logger.error(f"[BackendAPI] {method} {path} 超时")
        return {"success": False, "msg": "后端接口超时"}
    except httpx.RequestError as e:
        logger.error(f"[BackendAPI] {method} {path} 请求失败: {str(e)}")
        return {"success": False, "msg": f"后端接口请求失败: {str(e)}"}
    except Exception as e:
        logger.error(f"[BackendAPI] {method} {path} 异常: {str(e)}")
        return {"success": False, "msg": f"后端接口异常: {str(e)}"}


# ==================== 便捷方法 ====================

def reject_refund(token: str, shop_id: int, refund_id: int, reason: str) -> dict:
    """拒绝退款"""
    return call_backend_api_sync(
        "PUT", "/api/purchasesRefundsReject",
        token=token, shop_id=shop_id,
        params={"refundId": str(refund_id), "reason": reason},
    )


def approve_refund(token: str, shop_id: int, refund_id: int) -> dict:
    """批准退款"""
    return call_backend_api_sync(
        "PUT", "/api/purchasesRefundsApprove",
        token=token, shop_id=shop_id,
        params={"refundId": str(refund_id)},
    )


def checkin_game_session(token: str, shop_id: int, customer_id: int, customer_session_id: int) -> dict:
    """核销入座"""
    return call_backend_api_sync(
        "POST", "/api/gameSessionsCheckin",
        token=token, shop_id=shop_id,
        params={"customerId": str(customer_id), "customerSessionId": str(customer_session_id)},
    )


def finish_game_session(token: str, shop_id: int, game_session_id: int) -> dict:
    """结束游玩"""
    return call_backend_api_sync(
        "PUT", "/api/gameSessionsFinish",
        token=token, shop_id=shop_id,
        params={"gameSessionId": str(game_session_id)},
    )
