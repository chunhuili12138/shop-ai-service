"""
操作记录查询工具
使用 Pydantic V2 Schema 约束入参，LangChain StructuredTool 注册
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class OperationLogsQueryInput(BaseModel):
    """操作记录查询参数"""
    shop_id: int = Field(description="店铺ID")
    operator_id: Optional[int] = Field(default=None, description="操作人ID（可选）")
    action: Optional[str] = Field(
        default=None,
        description="操作类型: checkin=核销, inbound=入库, outbound=出库, refund_approve=退款批准, refund_reject=退款拒绝（可选）"
    )
    target_type: Optional[str] = Field(
        default=None,
        description="目标类型: customer=顾客, material=物料, purchase=购买, refund=退款（可选）"
    )
    start_date: Optional[str] = Field(default=None, description="开始日期，格式: yyyy-MM-dd（可选）")
    end_date: Optional[str] = Field(default=None, description="结束日期，格式: yyyy-MM-dd（可选）")
    limit: int = Field(default=20, description="返回数量，默认20")


# ==================== Tools ====================

@tool(args_schema=OperationLogsQueryInput)
def query_operation_logs(
    shop_id: int,
    operator_id: Optional[int] = None,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 20
) -> str:
    """
    查询操作记录。
    支持按操作人、操作类型、目标类型、时间范围筛选。
    返回操作人、操作类型、目标、详情、时间。
    用于查看谁在什么时间做了什么操作。
    """
    sql = """
        SELECT
            ol.id,
            ol.operator_id,
            s.name as operator_name,
            ol.action,
            ol.target_type,
            ol.target_id,
            ol.detail,
            ol.created_at
        FROM operation_logs ol
        LEFT JOIN staff s ON ol.operator_id = s.id
        WHERE ol.shop_id = :shop_id
    """

    params = {"shop_id": shop_id, "limit": limit}

    if operator_id:
        sql += " AND ol.operator_id = :operator_id"
        params["operator_id"] = operator_id

    if action:
        sql += " AND ol.action = :action"
        params["action"] = action

    if target_type:
        sql += " AND ol.target_type = :target_type"
        params["target_type"] = target_type

    if start_date:
        sql += " AND ol.created_at >= :start_date"
        params["start_date"] = start_date

    if end_date:
        sql += " AND ol.created_at <= :end_date"
        params["end_date"] = end_date

    sql += " ORDER BY ol.created_at DESC LIMIT :limit"

    try:
        results = execute_sql(sql, params)
        if not results:
            return "暂无操作记录"

        action_names = {
            "checkin": "核销",
            "finish": "结束游玩",
            "inbound": "物料入库",
            "outbound": "物料出库",
            "refund_approve": "退款批准",
            "refund_reject": "退款拒绝",
            "coupon_grant": "发放优惠券",
            "notification_send": "发送通知",
        }

        target_names = {
            "customer": "顾客",
            "material": "物料",
            "purchase": "购买记录",
            "refund": "退款记录",
            "customer_session": "顾客场次",
            "game_session": "游戏场次",
            "coupon": "优惠券",
            "notification": "通知",
        }

        output = "操作记录:\n"
        for row in results:
            operator = row["operator_name"] or f"ID:{row['operator_id']}"
            action_name = action_names.get(row["action"], row["action"])
            target_name = target_names.get(row["target_type"], row["target_type"])
            
            # 解析详情
            detail_str = ""
            if row["detail"]:
                try:
                    import json
                    detail = json.loads(row["detail"])
                    if detail:
                        detail_items = [f"{k}={v}" for k, v in detail.items()]
                        detail_str = f" ({', '.join(detail_items)})"
                except:
                    detail_str = f" ({row['detail']})"
            
            output += f"- [{row['id']}] {operator} {action_name} {target_name}[{row['target_id']}]{detail_str} - {row['created_at']}\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"
