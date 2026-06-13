"""
认证模块
调用后台管理系统验证 Token，支持缓存
"""

import httpx
from typing import Optional, Tuple
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.config import settings
from app.common.user_context import UserContext

# Token 缓存 {cache_key: (user_context, expire_time)}
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
    from fastapi import HTTPException

    print(f"[Auth] 验证 Token - token: {token[:10]}..., shop_id: {shop_id}")

    # 1. 检查缓存
    cache_key = f"{token}:{shop_id}"
    if cache_key in _token_cache:
        user_context, expire_time = _token_cache[cache_key]
        if datetime.now() < expire_time:
            print(f"[Auth] 命中缓存 - user_id: {user_context.user_id}")
            return user_context
        else:
            print(f"[Auth] 缓存已过期")
            del _token_cache[cache_key]

    # 2. 构建 Authorization header
    if shop_id:
        authorization = f"Bearer-{shop_id}-{token}"
    else:
        authorization = f"Bearer {token}"

    # 3. 调用后台接口
    try:
        url = f"{settings.BACKEND_URL}/api/auth/info"
        print(f"[Auth] 调用后台接口 - url: {url}")
        
        # 配置 httpx 客户端
        transport = httpx.AsyncHTTPTransport(
            retries=2,  # 重试次数
            verify=False,  # 禁用 SSL 验证（开发环境）
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

        print(f"[Auth] 后台接口响应 - status: {response.status_code}")

        if response.status_code != 200:
            print(f"[Auth] Token 验证失败 - status: {response.status_code}")
            raise HTTPException(status_code=401, detail="Token 无效或已过期")

        data = response.json()

        if not data.get("success"):
            print(f"[Auth] Token 验证失败 - msg: {data.get('msg')}")
            raise HTTPException(status_code=401, detail=data.get("msg", "认证失败"))

        user_data = data.get("data", {})
        print(f"[Auth] Token 验证成功 - userId: {user_data.get('userId')}, username: {user_data.get('username')}")

    except httpx.RequestError as e:
        # 后台服务不可用时，返回错误
        print(f"[Auth] 后台服务不可用 - error: {str(e)}")
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
        # 如果没有指定 shop_id，使用第一个店铺
        actual_shop_id = shops[0].get("id") if shops else 0
        actual_shop_name = shops[0].get("name", "") if shops else ""
    else:
        # 查找指定 shop_id 的店铺名称
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
    )

    # 5. 缓存
    _token_cache[cache_key] = (user_context, datetime.now() + _cache_ttl)
    print(f"[Auth] 缓存 Token - user_id: {user_context.user_id}, ttl: {settings.TOKEN_CACHE_TTL}s")

    return user_context


def clear_token_cache(token: str = None):
    """
    清除 Token 缓存

    Args:
        token: 指定 Token（可选，不指定则清除全部）
    """
    if token:
        # 清除指定 Token 的所有缓存
        keys_to_delete = [k for k in _token_cache.keys() if k.startswith(token)]
        for key in keys_to_delete:
            del _token_cache[key]
    else:
        # 清除全部缓存
        _token_cache.clear()


def get_cache_stats() -> dict:
    """
    获取缓存统计信息

    Returns:
        缓存统计字典
    """
    now = datetime.now()
    valid_count = sum(1 for _, (_, exp) in _token_cache.items() if now < exp)
    expired_count = len(_token_cache) - valid_count

    return {
        "total": len(_token_cache),
        "valid": valid_count,
        "expired": expired_count,
        "cache_ttl_seconds": settings.TOKEN_CACHE_TTL,
    }
