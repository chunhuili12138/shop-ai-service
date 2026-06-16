"""
套餐查询工具
使用 Pydantic V2 Schema 约束入参，LangChain StructuredTool 注册
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class PackageQueryInput(BaseModel):
    """套餐查询参数"""
    shop_id: int = Field(description="店铺ID")
    package_type: Optional[str] = Field(
        default=None,
        description="套餐类型筛选: single=单次, week=周卡, month=月卡（可选）"
    )


class TopPackagesInput(BaseModel):
    """热销套餐查询参数"""
    shop_id: int = Field(description="店铺ID")
    limit: int = Field(default=5, description="返回数量，默认5")


# ==================== Tools ====================

@tool(args_schema=PackageQueryInput)
def query_packages(shop_id: int, package_type: Optional[str] = None) -> str:
    """
    查询店铺套餐列表。
    支持按类型筛选（单次/周卡/月卡），返回套餐名称、类型、价格和时长。
    """
    sql = """
        SELECT
            id,
            name,
            type,
            price,
            duration_minutes,
            max_people_per_session,
            is_active
        FROM packages
        WHERE shop_id = :shop_id AND (is_deleted = 0 OR is_deleted IS NULL)
    """

    params = {"shop_id": shop_id}

    if package_type:
        type_map = {"single": 1, "week": 2, "month": 3}
        if package_type in type_map:
            sql += " AND type = :type"
            params["type"] = type_map[package_type]

    sql += " ORDER BY type, price"

    try:
        results = execute_sql(sql, params)
        if not results:
            return "暂无套餐数据"

        type_names = {1: "单次", 2: "周卡", 3: "月卡"}
        status_names = {0: "已下架", 1: "在售"}

        output = "套餐列表:\n"
        for row in results:
            name = row['name']
            type_name = type_names.get(row["type"], "未知")
            price = row['price']
            duration = row['duration_minutes']
            status = status_names.get(row["is_active"], "未知")
            output += f"- {name}（{type_name}）: ¥{price:.2f}，{duration}分钟 [{status}]\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=TopPackagesInput)
def query_top_packages(shop_id: int, limit: int = 5) -> str:
    """
    查询本月热销套餐排行榜。
    返回套餐名称、销量和销售额，按销量降序排列。
    """
    sql = """
        SELECT
            p.name as package_name,
            COUNT(*) as sales_count,
            SUM(pu.paid_amount) as total_amount
        FROM purchases pu
        JOIN packages p ON pu.package_id = p.id
        WHERE pu.shop_id = :shop_id
        AND pu.status = 1
        AND YEAR(pu.created_at) = YEAR(NOW())
        AND MONTH(pu.created_at) = MONTH(NOW())
        GROUP BY p.id
        ORDER BY sales_count DESC
        LIMIT :limit
    """

    try:
        results = execute_sql(sql, {"shop_id": shop_id, "limit": limit})
        if not results:
            return "暂无销售数据"

        output = "本月热销套餐:\n"
        for i, row in enumerate(results, 1):
            name = row['package_name']
            count = row['sales_count']
            amount = row['total_amount']
            output += f"{i}. {name}: {count}单，¥{amount:.2f}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"
