"""
auth.py 单元测试
测试 Token 缓存、解析、SSL 配置
"""

import pytest
from unittest.mock import patch, MagicMock
from app.common.auth import parse_authorization, clear_token_cache, get_cache_stats


class TestParseAuthorization:
    """测试 Authorization header 解析"""

    def test_bearer_dash_format(self):
        """Bearer-{shopId}-{token} 格式"""
        token, shop_id = parse_authorization("Bearer-5-abc123def")
        assert token == "abc123def"
        assert shop_id == 5

    def test_bearer_space_format(self):
        """Bearer {token} 格式（超管）"""
        token, shop_id = parse_authorization("Bearer abc123def")
        assert token == "abc123def"
        assert shop_id is None

    def test_bearer_space_with_shopid(self):
        """Bearer {shopId}-{token} 格式"""
        token, shop_id = parse_authorization("Bearer 3-mytoken123")
        assert token == "mytoken123"
        assert shop_id == 3

    def test_invalid_format(self):
        """无效格式直接返回原文"""
        token, shop_id = parse_authorization("some-random-string")
        assert token == "some-random-string"
        assert shop_id is None

    def test_bearer_dash_no_shopid(self):
        """Bearer- 后面没有 shopId"""
        token, shop_id = parse_authorization("Bearer-notanumber-token123")
        assert token == "notanumber-token123"
        assert shop_id is None

    def test_token_with_hyphens(self):
        """token 本身包含连字符"""
        token, shop_id = parse_authorization("Bearer-5-abc-def-ghi")
        assert token == "abc-def-ghi"
        assert shop_id == 5


class TestTokenCache:
    """测试 Token 缓存管理"""

    def test_clear_all_cache(self):
        """清除全部缓存"""
        from app.common.auth import _token_cache
        _token_cache["test-key"] = ("test-value", None)
        clear_token_cache()
        assert len(_token_cache) == 0

    def test_get_cache_stats(self):
        """获取缓存统计"""
        stats = get_cache_stats()
        assert "total" in stats
        assert "valid" in stats
        assert "expired" in stats
        assert "cache_ttl_seconds" in stats
        assert "max_size" in stats
