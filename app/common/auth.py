"""
认证模块
调用后台管理系统验证 Token，支持缓存
"""

import httpx
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.config import settings
from app.common.user_context import UserContext

logger = logging.getLogger(__name__)

# Token 缓存：使用 TTLCache 限制最大条目数，自动淘汰过期和最久未用的条目
try:
    from cachetools import TTLCache
    _token_cache = TTLCache(maxsize=10000, ttl=settings.TOKEN_CACHE_TTL)
except ImportError:
    # 降级为普通 dict（无大小限制，仅开发环境使用）
    logger.warning("cachetools 未安装，Token 缓存无大小限制，请执行: pip install cachetools")
    _token_cache = {}
    _cache_ttl = timedelta(seconds=settings.TOKEN_CACHE_TTL)


def parse_authorization(authorization: str) -> Tuple[str, Optional[int]]:
    """
    解析 Authorization header

    支持两种格式：
    - 超管/未选店铺: "Bearer {token}"
    - 已选店铺:      "Bearer-{shopId}-{token}"

    Returns:
        (token, shop_id) 元组
    """
    if authorization.startswith("Bearer-"):
        # 格式: Bearer-{shopId}-{token}
        rest = authorization[7:]
        parts = rest.split("-", 1)
        if len(parts) == 2:
            try:
                shop_id = int(parts[0])
                token = parts[1]
                return token, shop_id
            except ValueError:
                return rest, None
        return rest, None
    elif authorization.startswith("Bearer "):
        # 格式: Bearer {token} 或 Bearer {shopId}-{token}
        rest = authorization[7:]
        parts = rest.split("-", 1)
        if len(parts) == 2:
            try:
                shop_id = int(parts[0])
                token = rest[len(parts[0]) + 1:]
                return token, shop_id
            except ValueError:
                return rest, None
        return rest, None
    else:
        return authorization, None


async def verify_token(token: str, shop_id: Optional[int] = None) -> UserContext:
    """
    验证 Token 并获取用户信息（带缓存）

    Args:
        token: 用户 Token
        shop_id: 店铺 ID（可选）

    Returns:
        UserContext 用户上下文

    Raises:
        HTTPException: Token 无效或无权限
    """
    logger.debug(f"验证 Token - token: {token[:8]}..., shop_id: {shop_id}")

    # 1. 检查缓存
    cache_key = f"{token}:{shop_id}"

    if isinstance(_token_cache, dict):
        # 普通 dict 模式：手动检查过期
        if cache_key in _token_cache:
            user_context, expire_time = _token_cache[cache_key]
            if datetime.now() < expire_time:
                logger.debug(f"命中缓存 - user_id: {user_context.user_id}")
                return user_context
            else:
                logger.debug("缓存已过期")
                del _token_cache[cache_key]
    else:
        # TTLCache 模式：自动过期
        if cache_key in _token_cache:
            logger.debug(f"命中缓存 - user_id: {_token_cache[cache_key].user_id}")
            return _token_cache[cache_key]

    # 2. 构建 Authorization header
    if shop_id:
        authorization = f"Bearer-{shop_id}-{token}"
    else:
        authorization = f"Bearer {token}"

    # 3. 调用后台接口
    try:
        url = f"{settings.BACKEND_URL}/api/auth/info"
        logger.debug(f"调用后台接口 - url: {url}")

        # 根据环境决定是否禁用 SSL 验证
        is_dev = settings.ENVIRONMENT in ("development", "dev", "local")
        transport = httpx.AsyncHTTPTransport(
            retries=2,
            verify=not is_dev,  # 生产环境启用 SSL 验证
        )

        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
        ) as client:
            response = await client.get(
                url,
                headers={"Authorization": authorization},
            )

        logger.debug(f"后台接口响应 - status: {response.status_code}")

        if response.status_code != 200:
            logger.warning(f"Token 验证失败 - status: {response.status_code}")
            raise HTTPException(status_code=401, detail="Token 无效或已过期")

        data = response.json()

        if not data.get("success"):
            logger.warning(f"Token 验证失败 - msg: {data.get('msg')}")
            raise HTTPException(status_code=401, detail=data.get("msg", "认证失败"))

        user_data = data.get("data", {})
        logger.info(f"Token 验证成功 - userId: {user_data.get('userId')}, username: {user_data.get('username')}")

    except httpx.RequestError as e:
        logger.error(f"后台服务不可用 - error: {str(e)}")
        raise HTTPException(status_code=503, detail=f"认证服务不可用: {str(e)}")

    # 4. 构建 UserContext
    roles = user_data.get("roles", [])
    role = roles[0] if roles else "guest"

    # 顾客端特殊处理
    user_type = user_data.get("userType", "")
    if user_type == "customer":
        role = "顾客"

    # 获取店铺列表
    shops = user_data.get("shops", [])
    actual_shop_id = shop_id
    actual_shop_name = ""
    if not actual_shop_id and shops:
        actual_shop_id = shops[0].get("id") if shops else 0
        actual_shop_name = shops[0].get("name", "") if shops else ""
    else:
        for shop in shops:
            if shop.get("id") == actual_shop_id:
                actual_shop_name = shop.get("name", "")
                break

    user_context = UserContext(
        user_id=user_data.get("userId", 0),
        shop_id=actual_shop_id or 0,
        role=role,
        permissions=user_data.get("permissions", []),
        is_super_admin=user_data.get("isSuperAdmin", False),
        username=user_data.get("username", ""),
        display_name=user_data.get("nickname", ""),
        shop_name=actual_shop_name,
        token=token,
    )

    # 5. 缓存
    if isinstance(_token_cache, dict):
        _token_cache[cache_key] = (user_context, datetime.now() + _cache_ttl)
    else:
        _token_cache[cache_key] = user_context

    logger.debug(f"缓存 Token - user_id: {user_context.user_id}, ttl: {settings.TOKEN_CACHE_TTL}s")

    return user_context


def clear_token_cache(token: str = None):
    """
    清除 Token 缓存

    Args:
        token: 指定 Token（可选，不指定则清除全部）
    """
    if token:
        keys_to_delete = [k for k in _token_cache.keys() if k.startswith(token)]
        for key in keys_to_delete:
            del _token_cache[key]
    else:
        _token_cache.clear()


def get_cache_stats() -> dict:
    """获取缓存统计信息"""
    now = datetime.now()

    if isinstance(_token_cache, dict):
        valid_count = sum(1 for _, (_, exp) in _token_cache.items() if now < exp)
        expired_count = len(_token_cache) - valid_count
    else:
        # TTLCache 没有过期时间可查
        valid_count = len(_token_cache)
        expired_count = 0

    return {
        "total": len(_token_cache),
        "valid": valid_count,
        "expired": expired_count,
        "cache_ttl_seconds": settings.TOKEN_CACHE_TTL,
        "max_size": getattr(_token_cache, 'maxsize', 'unlimited'),
    }
