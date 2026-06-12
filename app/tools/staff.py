"""
员工查询工具
使用 Pydantic V2 Schema 约束入参，LangChain StructuredTool 注册
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class StaffPerformanceInput(BaseModel):
    """员工绩效查询参数"""
    shop_id: int = Field(description="店铺ID")
    date_range: str = Field(
        default="month",
        description="时间范围: today=今天, week=本周, month=本月"
    )


class StaffListInput(BaseModel):
    """员工列表查询参数"""
    shop_id: int = Field(description="店铺ID")
    keyword: Optional[str] = Field(default=None, description="员工姓名关键词（可选）")


# ==================== Tools ====================

@tool(args_schema=StaffPerformanceInput)
def query_staff_performance(shop_id: int, date_range: str = "month") -> str:
    """
    查询员工绩效（核销数量统计）。
    统计指定时间范围内每位员工的核销次数和完成的游玩场次。
    """
    date_conditions = {
        "today": "DATE(gs.end_time) = CURDATE()",
        "week": "YEARWEEK(gs.end_time) = YEARWEEK(NOW())",
        "month": "MONTH(gs.end_time) = MONTH(NOW()) AND YEAR(gs.end_time) = YEAR(NOW())",
    }

    where_clause = date_conditions.get(date_range, date_conditions["month"])

    sql = f"""
        SELECT
            s.name as staff_name,
            COUNT(*) as checkin_count,
            COUNT(CASE WHEN gs.status = 2 THEN 1 END) as completed_count
        FROM game_sessions gs
        JOIN staff s ON gs.staff_id = s.id
        WHERE gs.shop_id = :shop_id
        AND {where_clause}
        GROUP BY s.id
        ORDER BY checkin_count DESC
    """

    try:
        results = execute_sql(sql, {"shop_id": shop_id})
        if not results:
            return "暂无绩效数据"

        date_range_names = {"today": "今日", "week": "本周", "month": "本月"}
        period = date_range_names.get(date_range, "本月")

        output = f"{period}员工绩效:\n"
        for i, row in enumerate(results, 1):
            name = row['staff_name']
            checkin = row['checkin_count']
            completed = row['completed_count']
            output += f"{i}. {name}: 核销 {checkin} 次，完成 {completed} 场\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=StaffListInput)
def query_staff_list(shop_id: int, keyword: Optional[str] = None) -> str:
    """
    查询店铺员工列表。
    可按姓名关键词过滤，返回员工姓名、手机和状态。
    """
    sql = """
        SELECT
            s.id,
            s.name,
            s.phone,
            s.status,
            s.created_at
        FROM staff s
        JOIN staff_shops ss ON s.id = ss.staff_id
        WHERE ss.shop_id = :shop_id
        AND s.is_deleted = 0
    """

    params = {"shop_id": shop_id}
    if keyword:
        sql += " AND s.name LIKE :keyword"
        params["keyword"] = f"%{keyword}%"

    sql += " ORDER BY s.id"

    try:
        results = execute_sql(sql, params)
        if not results:
            return "未找到员工信息"

        status_map = {1: "在职", 2: "离职"}
        output = "员工列表:\n"
        for row in results:
            name = row['name']
            phone = row['phone'] or "未绑定"
            status = status_map.get(row["status"], "未知")
            output += f"- {name} | 手机: {phone} | 状态: {status}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"
