"""
Tool Calling 模块 — 工具注册表

所有工具在此统一注册，供 router.py 和 LangGraph Agent 使用。
每个工具使用 Pydantic V2 Schema 约束入参，LLM 自动获取 JSON Schema。

工具按业务实体分文件组织：
- revenue.py: 营收查询
- package.py: 套餐查询
- customer.py: 顾客查询
- trade.py: 交易查询和操作（购买、核销、退款）
- inventory.py: 库存查询和操作（入库、出库）
- staff.py: 员工查询
- queue.py: 排队管理
- coupon.py: 优惠券管理
- feedback.py: 评价反馈
- schedule.py: 排班考勤
- notification.py: 通知消息
- report.py: 财务报表和报告导出
- operation.py: 操作记录查询
- datetime_tools.py: 日期时间与计算工具
"""

from app.tools.revenue import query_revenue
from app.tools.package import query_packages, query_top_packages
from app.tools.customer import query_customer
from app.tools.trade import (
    query_purchases, query_game_sessions, query_refunds,
    refund_approve, refund_reject,
    game_session_checkin, game_session_finish,
    execute_refund_approve, execute_refund_reject,
    execute_game_session_checkin, execute_game_session_finish,
)
from app.tools.inventory import (
    query_inventory, query_low_stock,
    material_inbound, material_outbound,
    execute_material_inbound, execute_material_outbound,
)
from app.tools.staff import query_staff_performance, query_staff_list
from app.tools.queue import query_active_sessions
from app.tools.coupon import query_coupons, grant_coupon, query_coupon_usages, execute_grant_coupon
from app.tools.feedback import query_feedbacks, reply_feedback, execute_reply_feedback
from app.tools.schedule import query_staff_schedules, query_attendance_records
from app.tools.notification import query_notifications, send_notification, execute_send_notification
from app.tools.report import query_daily_snapshots, query_revenue_trend, export_report
from app.tools.operation import query_operation_logs
from app.tools.datetime_tools import get_current_datetime, calculate_date, calculator, format_datetime


# 所有工具列表（StructuredTool / BaseTool）
TOOLS = [
    # 营收
    query_revenue,
    # 套餐
    query_packages,
    query_top_packages,
    # 顾客
    query_customer,
    # 交易
    query_purchases,
    query_game_sessions,
    query_refunds,
    refund_approve,
    refund_reject,
    game_session_checkin,
    game_session_finish,
    # 库存
    query_inventory,
    query_low_stock,
    material_inbound,
    material_outbound,
    # 员工
    query_staff_performance,
    query_staff_list,
    # 排队管理
    query_active_sessions,
    # 优惠券管理
    query_coupons,
    grant_coupon,
    query_coupon_usages,
    # 评价反馈
    query_feedbacks,
    reply_feedback,
    # 排班考勤
    query_staff_schedules,
    query_attendance_records,
    # 通知消息
    query_notifications,
    send_notification,
    # 财务报表
    query_daily_snapshots,
    query_revenue_trend,
    export_report,
    # 操作记录
    query_operation_logs,
    # 日期时间与计算
    get_current_datetime,
    calculate_date,
    calculator,
    format_datetime,
]

# 工具名称 → 工具实例 映射
TOOL_MAP = {t.name: t for t in TOOLS}

# 写操作执行函数映射（确认后调用）
EXECUTE_FUNCTIONS = {
    "material_inbound": execute_material_inbound,
    "material_outbound": execute_material_outbound,
    "refund_approve": execute_refund_approve,
    "refund_reject": execute_refund_reject,
    "game_session_checkin": execute_game_session_checkin,
    "game_session_finish": execute_game_session_finish,
    "grant_coupon": execute_grant_coupon,
    "reply_feedback": execute_reply_feedback,
    "send_notification": execute_send_notification,
}

# 以下模块依赖 TOOLS / TOOL_MAP，必须在注册表定义之后再导入
from app.tools.parallel_executor import (
    ParallelToolExecutor,
    parallel_executor,
    execute_tools_parallel,
    execute_custom_parallel,
)
from app.tools.agent_loop import (
    AgentLoop,
    AgentLoopResult,
    get_agent_loop,
    run_agent,
    run_agent_simple,
)
from app.tools.permissions import (
    get_tools_for_role,
    get_allowed_tool_names,
    is_tool_allowed,
    get_all_roles,
    get_role_description,
)
from app.tools.prompt_templates import (
    get_system_prompt,
    get_prompt_for_role,
    get_default_prompt,
)

# 工具中文名映射（用于前端展示、session 存储、日志等）
TOOL_DISPLAY_NAMES = {
    "refund_reject": "退款拒绝",
    "refund_approve": "退款批准",
    "game_session_checkin": "核销入座",
    "game_session_finish": "结束游玩",
    "material_inbound": "物料入库",
    "material_outbound": "物料出库",
    "grant_coupon": "发放优惠券",
    "reply_feedback": "回复评价",
    "send_notification": "发送通知",
}

__all__ = [
    # 工具相关
    "TOOLS",
    "TOOL_MAP",
    "EXECUTE_FUNCTIONS",
    # 并行执行器
    "ParallelToolExecutor",
    "parallel_executor",
    "execute_tools_parallel",
    "execute_custom_parallel",
    # Agent 循环
    "AgentLoop",
    "AgentLoopResult",
    "get_agent_loop",
    "run_agent",
    "run_agent_simple",
    # 权限
    "get_tools_for_role",
    "get_allowed_tool_names",
    "is_tool_allowed",
    "get_all_roles",
    "get_role_description",
    # Prompt
    "get_system_prompt",
    "get_prompt_for_role",
    "get_default_prompt",
]
