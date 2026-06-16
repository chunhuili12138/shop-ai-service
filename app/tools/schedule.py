"""
排班考勤工具
查询排班表、查询考勤记录
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class SchedulesQueryInput(BaseModel):
    """排班查询参数"""
    shop_id: int = Field(description="店铺ID")
    date: Optional[str] = Field(
        default=None,
        description="日期筛选，格式: yyyy-MM-dd（可选，默认今天）"
    )
    staff_id: Optional[int] = Field(default=None, description="员工ID（可选）")


class AttendanceQueryInput(BaseModel):
    """考勤查询参数"""
    shop_id: int = Field(description="店铺ID")
    staff_id: Optional[int] = Field(default=None, description="员工ID（可选）")
    date: Optional[str] = Field(
        default=None,
        description="日期筛选，格式: yyyy-MM-dd（可选，默认今天）"
    )


# ==================== Tools ====================

@tool(args_schema=SchedulesQueryInput)
def query_staff_schedules(shop_id: int, date: Optional[str] = None, staff_id: Optional[int] = None) -> str:
    """
    查询员工排班表。
    返回员工姓名、排班日期、上班时间、下班时间。
    """
    sql = """
        SELECT
            ss.id,
            s.name as staff_name,
            ss.schedule_date,
            ss.start_time,
            ss.end_time,
            ss.type,
            ss.remark
        FROM staff_schedules ss
        JOIN staff s ON ss.staff_id = s.id
        WHERE ss.shop_id = :shop_id
    """

    params = {"shop_id": shop_id}

    if date:
        sql += " AND ss.schedule_date = :date"
        params["date"] = date
    else:
        sql += " AND ss.schedule_date = CURDATE()"

    if staff_id:
        sql += " AND ss.staff_id = :staff_id"
        params["staff_id"] = staff_id

    sql += " ORDER BY ss.start_time"

    try:
        results = execute_sql(sql, params)

        if not results:
            date_desc = date or "今天"
            return f"{date_desc}暂无排班"

        date_desc = date or "今天"
        output = f"{date_desc}排班表:\n"
        for row in results:
            staff = row["staff_name"]
            start = row["start_time"]
            end = row["end_time"]
            remark = row.get("remark", "")
            remark_str = f" ({remark})" if remark else ""
            output += f"- {staff}: {start} ~ {end}{remark_str}\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=AttendanceQueryInput)
def query_attendance_records(shop_id: int, staff_id: Optional[int] = None, date: Optional[str] = None) -> str:
    """
    查询员工考勤记录。
    返回员工姓名、日期、上班打卡时间、下班打卡时间、状态。
    """
    sql = """
        SELECT
            ar.id,
            s.name as staff_name,
            ar.date,
            ar.check_in_time,
            ar.check_out_time,
            ar.status
        FROM attendance_records ar
        JOIN staff s ON ar.staff_id = s.id
        WHERE ar.shop_id = :shop_id
    """

    params = {"shop_id": shop_id}

    if staff_id:
        sql += " AND ar.staff_id = :staff_id"
        params["staff_id"] = staff_id

    if date:
        sql += " AND ar.date = :date"
        params["date"] = date

    sql += " ORDER BY ar.date DESC, ar.check_in_time DESC"

    # 限制返回数量
    if not staff_id and not date:
        sql += " LIMIT 20"

    try:
        results = execute_sql(sql, params)

        if not results:
            return "暂无考勤记录"

        status_names = {1: "正常", 2: "迟到", 3: "早退", 4: "加班"}

        output = "考勤记录:\n"
        for row in results:
            staff = row["staff_name"]
            date_str = row["date"]
            check_in = row.get("check_in_time", "未打卡")
            check_out = row.get("check_out_time", "未打卡")
            status = status_names.get(row["status"], "未知")

            output += f"- {staff} [{date_str}]: {check_in} ~ {check_out} [{status}]\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"
