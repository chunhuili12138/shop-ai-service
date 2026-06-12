"""
MCP资源定义
将数据库Schema等信息暴露为MCP资源
"""

from typing import Any
from pydantic import BaseModel


class MCPResource(BaseModel):
    """MCP资源定义"""
    uri: str
    name: str
    description: str
    mime_type: str


# MCP资源定义
SHOP_MCP_RESOURCES = [
    MCPResource(
        uri="shop://schema/customers",
        name="顾客表结构",
        description="customers表的DDL结构",
        mime_type="text/plain",
    ),
    MCPResource(
        uri="shop://schema/packages",
        name="套餐表结构",
        description="packages表的DDL结构",
        mime_type="text/plain",
    ),
    MCPResource(
        uri="shop://schema/purchases",
        name="购买记录表结构",
        description="purchases表的DDL结构",
        mime_type="text/plain",
    ),
    MCPResource(
        uri="shop://schema/inventory",
        name="库存表结构",
        description="inventory表的DDL结构",
        mime_type="text/plain",
    ),
    MCPResource(
        uri="shop://config/permissions",
        name="权限配置",
        description="用户角色权限配置",
        mime_type="application/json",
    ),
]


def get_mcp_resources() -> list[MCPResource]:
    """获取所有MCP资源定义"""
    return SHOP_MCP_RESOURCES


def get_resource_content(uri: str) -> str:
    """获取MCP资源内容"""
    from app.nl2sql.schema import get_schema_info

    schema_map = {
        "shop://schema/customers": "customers表: id, nickname, phone, gender, birthday, source, shop_id, created_at",
        "shop://schema/packages": "packages表: id, name, type, duration_minutes, price, max_people_per_session, shop_id",
        "shop://schema/purchases": "purchases表: id, customer_id, package_id, channel, total_amount, paid_amount, status, shop_id, created_at",
        "shop://schema/inventory": "inventory表: id, material_id, quantity, shop_id",
    }

    return schema_map.get(uri, "资源不存在")
