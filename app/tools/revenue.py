"""
营收查询工具
使用 Pydantic V2 Schema 约束入参，LangChain StructuredTool 注册
"""

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class RevenueQueryInput(BaseModel):
    """营收查询参数"""
    shop_id: int = Field(description="店铺ID")
    date_range: str = Field(
        default="today",
        description="时间范围: today=今天, week=本周, month=本月, year=本年"
    )


# ==================== Tools ====================

@tool(args_schema=RevenueQueryInput)
def query_revenue(shop_id: int, date_range: str = "today") -> str:
    """
    查询店铺营收数据。
    支持按时间范围统计：今天(today)、本周(week)、本月(month)、本年(year)。
    返回订单数和总营收金额。
    """
    date_conditions = {
        "today": "DATE(created_at) = CURDATE()",
        "week": "YEARWEEK(created_at) = YEARWEEK(NOW())",
        "month": "MONTH(created_at) = MONTH(NOW()) AND YEAR(created_at) = YEAR(NOW())",
        "year": "YEAR(created_at) = YEAR(NOW())",
    }

    date_range_names = {
        "today": "今日",
        "week": "本周",
        "month": "本月",
        "year": "本年",
    }

    where_clause = date_conditions.get(date_range, date_conditions["today"])
    period_name = date_range_names.get(date_range, "今日")

    sql = f"""
        SELECT
            COUNT(*) as order_count,
            COALESCE(SUM(paid_amount), 0) as total_revenue
        FROM purchases
        WHERE shop_id = :shop_id
        AND status = 1
        AND {where_clause}
    """

    try:
        results = execute_sql(sql, {"shop_id": shop_id})
        if results:
            row = results[0]
            order_count = row['order_count']
            total_revenue = row['total_revenue']
            
            if order_count == 0:
                return f"{period_name}暂无营收数据"
            
            return f"{period_name}营收：订单 {order_count} 单，总营收 ¥{total_revenue:.2f}"
        return f"{period_name}暂无营收数据"
    except Exception as e:
        return f"查询失败: {str(e)}"
