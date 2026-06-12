"""
MCP工具定义
将店铺API封装为MCP标准工具
"""

from typing import Any
from pydantic import BaseModel, Field


class MCPTool(BaseModel):
    """MCP工具定义"""
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: str  # 处理函数名


# 店铺API的MCP工具定义
SHOP_MCP_TOOLS = [
    MCPTool(
        name="query_customer",
        description="查询顾客信息，支持按姓名或手机号搜索",
        input_schema={
            "type": "object",
            "properties": {
                "shop_id": {"type": "integer", "description": "店铺ID"},
                "keyword": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["shop_id", "keyword"],
        },
        handler="app.tools.customer.query_customer",
    ),
    MCPTool(
        name="query_revenue",
        description="查询店铺营收数据",
        input_schema={
            "type": "object",
            "properties": {
                "shop_id": {"type": "integer", "description": "店铺ID"},
                "date_range": {
                    "type": "string",
                    "enum": ["today", "week", "month", "year"],
                    "description": "时间范围",
                },
            },
            "required": ["shop_id"],
        },
        handler="app.tools.revenue.query_revenue",
    ),
    MCPTool(
        name="query_inventory",
        description="查询库存信息",
        input_schema={
            "type": "object",
            "properties": {
                "shop_id": {"type": "integer", "description": "店铺ID"},
                "keyword": {"type": "string", "description": "物料名称"},
            },
            "required": ["shop_id"],
        },
        handler="app.tools.inventory.query_inventory",
    ),
    MCPTool(
        name="query_low_stock",
        description="查询库存预警（低于最低库存的物料）",
        input_schema={
            "type": "object",
            "properties": {
                "shop_id": {"type": "integer", "description": "店铺ID"},
            },
            "required": ["shop_id"],
        },
        handler="app.tools.inventory.query_low_stock",
    ),
]


def get_mcp_tools() -> list[MCPTool]:
    """获取所有MCP工具定义"""
    return SHOP_MCP_TOOLS


def get_tool_by_name(name: str) -> MCPTool | None:
    """根据名称获取MCP工具"""
    for tool in SHOP_MCP_TOOLS:
        if tool.name == name:
            return tool
    return None
