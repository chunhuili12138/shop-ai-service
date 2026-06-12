"""
财务报表工具
查询每日经营快照、查询营收趋势、导出分析报告
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class DailySnapshotsQueryInput(BaseModel):
    """每日经营快照查询参数"""
    shop_id: int = Field(description="店铺ID")
    start_date: Optional[str] = Field(
        default=None,
        description="开始日期，格式: yyyy-MM-dd（可选，默认最近7天）"
    )
    end_date: Optional[str] = Field(
        default=None,
        description="结束日期，格式: yyyy-MM-dd（可选，默认今天）"
    )


class RevenueTrendQueryInput(BaseModel):
    """营收趋势查询参数"""
    shop_id: int = Field(description="店铺ID")
    granularity: Optional[str] = Field(
        default="day",
        description="粒度: day=按日, week=按周, month=按月"
    )
    days: Optional[int] = Field(default=30, description="查询天数，默认30天")


class ExportReportInput(BaseModel):
    """导出报告参数"""
    shop_id: int = Field(description="店铺ID")
    report_type: str = Field(
        description="报告类型: daily=日报, weekly=周报, monthly=月报, custom=自定义"
    )
    start_date: Optional[str] = Field(default=None, description="开始日期，格式: yyyy-MM-dd")
    end_date: Optional[str] = Field(default=None, description="结束日期，格式: yyyy-MM-dd")


# ==================== Tools ====================

@tool(args_schema=DailySnapshotsQueryInput)
def query_daily_snapshots(shop_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """
    查询每日经营快照。
    返回每日营业额、订单数、新顾客数、核销数等关键指标。
    """
    sql = """
        SELECT
            snapshot_date,
            sales_total,
            orders_count,
            new_customers,
            checkins_count,
            inventory_warns
        FROM daily_snapshots
        WHERE shop_id = :shop_id
    """

    params = {"shop_id": shop_id}

    if start_date:
        sql += " AND snapshot_date >= :start_date"
        params["start_date"] = start_date

    if end_date:
        sql += " AND snapshot_date <= :end_date"
        params["end_date"] = end_date

    # 默认查询最近7天
    if not start_date and not end_date:
        sql += " AND snapshot_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"

    sql += " ORDER BY snapshot_date DESC"

    try:
        results = execute_sql(sql, params)

        if not results:
            return "暂无经营快照数据"

        output = "经营快照:\n"
        for row in results:
            date = row["snapshot_date"]
            sales = row.get("sales_total", 0) or 0
            orders = row.get("orders_count", 0) or 0
            new_customers = row.get("new_customers", 0) or 0
            checkins = row.get("checkins_count", 0) or 0
            warns = row.get("inventory_warns", 0) or 0

            output += f"- {date}: 营业额 ¥{sales:.2f} | 订单 {orders} 单 | 新客 {new_customers} 人 | 核销 {checkins} 次"
            if warns > 0:
                output += f" | 库存预警 {warns} 项"
            output += "\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=RevenueTrendQueryInput)
def query_revenue_trend(shop_id: int, granularity: str = "day", days: int = 30) -> str:
    """
    查询营收趋势。
    按日/周/月统计营收数据，返回趋势信息。
    """
    # 根据粒度选择不同的SQL
    if granularity == "week":
        group_by = "YEARWEEK(created_at)"
        date_format = "DATE(DATE_SUB(created_at, INTERVAL WEEKDAY(created_at) DAY))"
    elif granularity == "month":
        group_by = "DATE_FORMAT(created_at, '%Y-%m')"
        date_format = "DATE_FORMAT(created_at, '%Y-%m-01')"
    else:  # day
        group_by = "DATE(created_at)"
        date_format = "DATE(created_at)"

    sql = f"""
        SELECT
            {date_format} as period,
            COUNT(*) as order_count,
            SUM(paid_amount) as total_revenue,
            COUNT(DISTINCT customer_id) as unique_customers
        FROM purchases
        WHERE shop_id = :shop_id
        AND status = 1
        AND created_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
        GROUP BY {group_by}
        ORDER BY period DESC
    """

    try:
        results = execute_sql(sql, {"shop_id": shop_id, "days": days})

        if not results:
            return "暂无营收数据"

        granularity_names = {"day": "日", "week": "周", "month": "月"}
        granularity_name = granularity_names.get(granularity, "日")

        output = f"营收趋势（按{granularity_name}）:\n"
        for row in results:
            period = row["period"]
            revenue = row.get("total_revenue", 0) or 0
            orders = row.get("order_count", 0) or 0
            customers = row.get("unique_customers", 0) or 0

            output += f"- {period}: 营收 ¥{revenue:.2f} | 订单 {orders} 单 | 顾客 {customers} 人\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=ExportReportInput)
def export_report(
    shop_id: int,
    report_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """
    导出经营分析报告。
    支持日报、周报、月报、自定义报告。
    返回 Markdown 格式的报告内容。
    """
    import datetime
    
    # 确定日期范围
    today = datetime.date.today()
    
    if report_type == "daily":
        if not start_date:
            start_date = str(today)
        if not end_date:
            end_date = str(today)
        report_title = f"日报 ({start_date})"
    elif report_type == "weekly":
        if not start_date:
            start_date = str(today - datetime.timedelta(days=today.weekday()))
        if not end_date:
            end_date = str(today)
        report_title = f"周报 ({start_date} ~ {end_date})"
    elif report_type == "monthly":
        if not start_date:
            start_date = str(today.replace(day=1))
        if not end_date:
            end_date = str(today)
        report_title = f"月报 ({start_date} ~ {end_date})"
    else:
        if not start_date:
            start_date = str(today - datetime.timedelta(days=30))
        if not end_date:
            end_date = str(today)
        report_title = f"自定义报告 ({start_date} ~ {end_date})"
    
    # 查询数据
    report_parts = []
    report_parts.append(f"# 经营{report_title}")
    report_parts.append("")
    
    # 1. 营收概况
    revenue_sql = """
        SELECT 
            COUNT(*) as order_count,
            SUM(paid_amount) as total_revenue,
            COUNT(DISTINCT customer_id) as unique_customers
        FROM purchases
        WHERE shop_id = :shop_id
        AND status = 1
        AND created_at >= :start_date
        AND created_at <= :end_date
    """
    revenue = execute_sql(revenue_sql, {
        "shop_id": shop_id,
        "start_date": start_date,
        "end_date": end_date
    })
    
    if revenue and revenue[0]:
        r = revenue[0]
        report_parts.append("## 营收概况")
        report_parts.append(f"- 总营收: ¥{r.get('total_revenue', 0) or 0:.2f}")
        report_parts.append(f"- 订单数: {r.get('order_count', 0) or 0} 单")
        report_parts.append(f"- 顾客数: {r.get('unique_customers', 0) or 0} 人")
        report_parts.append("")
    
    # 2. 热销套餐
    packages_sql = """
        SELECT 
            p.name as package_name,
            COUNT(*) as sales_count,
            SUM(pu.paid_amount) as total_amount
        FROM purchases pu
        JOIN packages p ON pu.package_id = p.id
        WHERE pu.shop_id = :shop_id
        AND pu.status = 1
        AND pu.created_at >= :start_date
        AND pu.created_at <= :end_date
        GROUP BY p.id
        ORDER BY sales_count DESC
        LIMIT 5
    """
    packages = execute_sql(packages_sql, {
        "shop_id": shop_id,
        "start_date": start_date,
        "end_date": end_date
    })
    
    if packages:
        report_parts.append("## 热销套餐 TOP5")
        for i, p in enumerate(packages, 1):
            report_parts.append(f"{i}. {p['package_name']}: {p['sales_count']}单, ¥{p['total_amount']:.2f}")
        report_parts.append("")
    
    # 3. 新顾客
    new_customers_sql = """
        SELECT COUNT(*) as count
        FROM customers
        WHERE shop_id = :shop_id
        AND created_at >= :start_date
        AND created_at <= :end_date
    """
    new_customers = execute_sql(new_customers_sql, {
        "shop_id": shop_id,
        "start_date": start_date,
        "end_date": end_date
    })
    
    if new_customers and new_customers[0]:
        report_parts.append("## 新顾客")
        report_parts.append(f"- 新增顾客: {new_customers[0]['count']} 人")
        report_parts.append("")
    
    # 4. 库存预警
    inventory_sql = """
        SELECT 
            m.name as material_name,
            i.quantity,
            m.min_stock
        FROM inventory i
        JOIN materials m ON i.material_id = m.id
        WHERE i.shop_id = :shop_id
        AND i.quantity <= m.min_stock
    """
    inventory = execute_sql(inventory_sql, {"shop_id": shop_id})
    
    if inventory:
        report_parts.append("## 库存预警")
        for inv in inventory:
            report_parts.append(f"- {inv['material_name']}: 当前{inv['quantity']}, 最低{inv['min_stock']}")
        report_parts.append("")
    
    # 5. 员工绩效
    staff_sql = """
        SELECT 
            s.name as staff_name,
            COUNT(*) as checkin_count
        FROM game_sessions gs
        JOIN staff s ON gs.staff_id = s.id
        WHERE gs.shop_id = :shop_id
        AND gs.start_time >= :start_date
        AND gs.start_time <= :end_date
        GROUP BY gs.staff_id
        ORDER BY checkin_count DESC
        LIMIT 5
    """
    staff = execute_sql(staff_sql, {
        "shop_id": shop_id,
        "start_date": start_date,
        "end_date": end_date
    })
    
    if staff:
        report_parts.append("## 员工绩效 TOP5")
        for i, s in enumerate(staff, 1):
            report_parts.append(f"{i}. {s['staff_name']}: 核销 {s['checkin_count']} 次")
        report_parts.append("")
    
    # 生成报告
    report = "\n".join(report_parts)
    return report
