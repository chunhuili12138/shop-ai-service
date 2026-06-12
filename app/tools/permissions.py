"""
角色权限配置模块
定义角色-工具映射，提供工具权限过滤功能
"""

from typing import List, Dict, Set
from langchain_core.tools import BaseTool
from app.tools import TOOLS


# ==================== 角色-工具映射 ====================

ROLE_TOOL_PERMISSIONS: Dict[str, List[str]] = {
    "店长": [
        # 营收相关
        "query_revenue",
        # 套餐相关
        "query_packages",
        "query_top_packages",
        # 顾客相关
        "query_customer",
        # 交易相关
        "query_purchases",
        "query_game_sessions",
        "query_refunds",
        "refund_approve",
        "refund_reject",
        "game_session_checkin",
        "game_session_finish",
        # 库存相关
        "query_inventory",
        "query_low_stock",
        "material_inbound",
        "material_outbound",
        # 员工相关
        "query_staff_performance",
        "query_staff_list",
        # 排队管理
        "query_active_sessions",
        # 优惠券管理
        "query_coupons",
        "grant_coupon",
        "query_coupon_usages",
        # 评价反馈
        "query_feedbacks",
        "reply_feedback",
        # 排班考勤
        "query_staff_schedules",
        "query_attendance_records",
        # 通知消息
        "query_notifications",
        "send_notification",
        # 财务报表
        "query_daily_snapshots",
        "query_revenue_trend",
        "export_report",
        # 操作记录
        "query_operation_logs",
    ],
    "导玩员": [
        # 顾客相关
        "query_customer",
        # 交易相关
        "query_purchases",
        "query_game_sessions",
        "game_session_checkin",
        "game_session_finish",
        # 排队管理
        "query_active_sessions",
        # 评价反馈
        "query_feedbacks",
        "reply_feedback",
    ],
    "仓管": [
        # 库存相关
        "query_inventory",
        "query_low_stock",
        "material_inbound",
        "material_outbound",
    ],
    "财务": [
        # 营收相关
        "query_revenue",
        "query_top_packages",
        # 交易相关
        "query_refunds",
        "refund_approve",
        "refund_reject",
        # 财务报表
        "query_daily_snapshots",
        "query_revenue_trend",
        "export_report",
        # 操作记录
        "query_operation_logs",
    ],
    "guest": [
        # 访客只能查询基本营收
        "query_revenue",
    ],
}


# ==================== 角色描述 ====================

ROLE_DESCRIPTIONS: Dict[str, str] = {
    "店长": "店铺管理者，拥有所有数据访问权限",
    "导玩员": "顾客服务人员，可以查询顾客信息、核销记录、排队状态、评价反馈",
    "仓管": "库存管理人员，可以查询库存和物料信息",
    "财务": "财务人员，可以查询营收、支出和财务报表",
    "guest": "访客，只有基本查询权限",
}


# ==================== 工具权限函数 ====================

def get_allowed_tool_names(role: str) -> List[str]:
    """
    获取角色允许的工具名称列表
    
    Args:
        role: 角色名称
    
    Returns:
        允许的工具名称列表
    """
    return ROLE_TOOL_PERMISSIONS.get(role, ROLE_TOOL_PERMISSIONS["guest"])


def get_tools_for_role(role: str) -> List[BaseTool]:
    """
    获取角色可用的工具列表
    
    Args:
        role: 角色名称
    
    Returns:
        可用的工具列表
    """
    allowed_names = set(get_allowed_tool_names(role))
    return [tool for tool in TOOLS if tool.name in allowed_names]


def is_tool_allowed(role: str, tool_name: str) -> bool:
    """
    检查角色是否允许使用指定工具
    
    Args:
        role: 角色名称
        tool_name: 工具名称
    
    Returns:
        是否允许
    """
    allowed_names = get_allowed_tool_names(role)
    return tool_name in allowed_names


def get_all_roles() -> List[str]:
    """
    获取所有角色列表
    
    Returns:
        角色名称列表
    """
    return list(ROLE_TOOL_PERMISSIONS.keys())


def get_role_description(role: str) -> str:
    """
    获取角色描述
    
    Args:
        role: 角色名称
    
    Returns:
        角色描述
    """
    return ROLE_DESCRIPTIONS.get(role, "未知角色")


def validate_role(role: str) -> bool:
    """
    验证角色是否有效
    
    Args:
        role: 角色名称
    
    Returns:
        是否有效
    """
    return role in ROLE_TOOL_PERMISSIONS


def get_tools_description_for_role(role: str) -> str:
    """
    获取角色可用工具的描述
    
    Args:
        role: 角色名称
    
    Returns:
        工具描述字符串
    """
    tools = get_tools_for_role(role)
    descriptions = []
    
    for tool in tools:
        desc = f"- **{tool.name}**: {tool.description}"
        if hasattr(tool, 'args_schema') and tool.args_schema:
            try:
                schema = tool.args_schema.schema()
                if 'properties' in schema:
                    params = list(schema['properties'].keys())
                    desc += f"\n  参数: {', '.join(params)}"
            except Exception:
                pass
        descriptions.append(desc)
    
    return "\n".join(descriptions) if descriptions else "无可用工具"
