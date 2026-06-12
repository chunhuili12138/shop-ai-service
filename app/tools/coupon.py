"""
优惠券管理工具
查询优惠券、发放优惠券、查询使用记录
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class CouponsQueryInput(BaseModel):
    """优惠券查询参数"""
    shop_id: int = Field(description="店铺ID")
    status: Optional[str] = Field(
        default=None,
        description="状态筛选: active=启用, disabled=禁用（可选）"
    )


class GrantCouponInput(BaseModel):
    """发放优惠券参数"""
    shop_id: int = Field(description="店铺ID")
    coupon_id: int = Field(description="优惠券ID")
    customer_ids: str = Field(description="顾客ID列表，逗号分隔")


class CouponUsagesQueryInput(BaseModel):
    """优惠券使用记录查询参数"""
    shop_id: int = Field(description="店铺ID")
    customer_id: Optional[int] = Field(default=None, description="顾客ID（可选）")
    limit: int = Field(default=10, description="返回数量，默认10")


# ==================== Tools ====================

@tool(args_schema=CouponsQueryInput)
def query_coupons(shop_id: int, status: Optional[str] = None) -> str:
    """
    查询店铺优惠券列表。
    返回优惠券名称、类型、面值、库存、有效期等信息。
    """
    sql = """
        SELECT
            id,
            name,
            type,
            value,
            min_order_amount,
            total_stock,
            remain_stock,
            valid_days,
            is_active,
            created_at
        FROM coupons
        WHERE shop_id = :shop_id
    """

    params = {"shop_id": shop_id}

    if status:
        if status == "active":
            sql += " AND is_active = 1"
        elif status == "disabled":
            sql += " AND is_active = 0"

    sql += " ORDER BY created_at DESC"

    try:
        results = execute_sql(sql, params)

        if not results:
            return "暂无优惠券"

        type_names = {1: "固定金额", 2: "百分比", 3: "兑换券"}
        status_names = {0: "已禁用", 1: "启用中"}

        output = "优惠券列表:\n"
        for row in results:
            type_name = type_names.get(row["type"], "未知")
            status_name = status_names.get(row["is_active"], "未知")

            # 格式化面值
            if row["type"] == 1:
                value_str = f"¥{row['value']}"
            elif row["type"] == 2:
                value_str = f"{row['value']}%"
            else:
                value_str = "兑换券"

            output += f"- [{row['id']}] {row['name']} ({type_name}): {value_str} | 库存: {row['remain_stock']}/{row['total_stock']} | 有效期: {row['valid_days']}天 [{status_name}]\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=GrantCouponInput)
def grant_coupon(shop_id: int, coupon_id: int, customer_ids: str) -> str:
    """
    发放优惠券给顾客。
    将优惠券发放给指定的顾客，顾客ID用逗号分隔。
    """
    # 先查询优惠券信息
    coupon_sql = """
        SELECT id, name, remain_stock, valid_days
        FROM coupons
        WHERE shop_id = :shop_id AND id = :coupon_id
    """

    try:
        coupon_results = execute_sql(coupon_sql, {"shop_id": shop_id, "coupon_id": coupon_id})

        if not coupon_results:
            return "优惠券不存在"

        coupon = coupon_results[0]

        # 解析顾客ID
        id_list = [int(id.strip()) for id in customer_ids.split(",") if id.strip()]

        if not id_list:
            return "请提供有效的顾客ID"

        # 检查库存
        if coupon["remain_stock"] < len(id_list):
            return f"库存不足，当前库存: {coupon['remain_stock']}，需要: {len(id_list)}"

        # 发放优惠券
        success_count = 0
        fail_count = 0

        for customer_id in id_list:
            try:
                insert_sql = """
                    INSERT INTO coupon_usages (coupon_id, customer_id, status, expires_at, created_at)
                    VALUES (:coupon_id, :customer_id, 1, DATE_ADD(NOW(), INTERVAL :valid_days DAY), NOW())
                """
                execute_sql(insert_sql, {
                    "coupon_id": coupon_id,
                    "customer_id": customer_id,
                    "valid_days": coupon["valid_days"]
                })
                success_count += 1
            except Exception:
                fail_count += 1

        # 更新库存
        update_sql = """
            UPDATE coupons SET remain_stock = remain_stock - :count
            WHERE id = :coupon_id
        """
        execute_sql(update_sql, {"count": success_count, "coupon_id": coupon_id})

        return f"发放完成: 成功 {success_count} 张，失败 {fail_count} 张"

    except Exception as e:
        return f"发放失败: {str(e)}"


@tool(args_schema=CouponUsagesQueryInput)
def query_coupon_usages(shop_id: int, customer_id: Optional[int] = None, limit: int = 10) -> str:
    """
    查询优惠券使用记录。
    返回顾客姓名、优惠券名称、状态、领取时间、过期时间。
    """
    sql = """
        SELECT
            cu.id,
            c.nickname as customer_name,
            cp.name as coupon_name,
            cu.status,
            cu.used_at,
            cu.expires_at,
            cu.created_at
        FROM coupon_usages cu
        JOIN coupons cp ON cu.coupon_id = cp.id
        LEFT JOIN customers c ON cu.customer_id = c.id
        WHERE cp.shop_id = :shop_id
    """

    params = {"shop_id": shop_id, "limit": limit}

    if customer_id:
        sql += " AND cu.customer_id = :customer_id"
        params["customer_id"] = customer_id

    sql += " ORDER BY cu.created_at DESC LIMIT :limit"

    try:
        results = execute_sql(sql, params)

        if not results:
            return "暂无优惠券使用记录"

        status_names = {1: "未使用", 2: "已使用", 3: "已过期"}

        output = "优惠券使用记录:\n"
        for row in results:
            status_name = status_names.get(row["status"], "未知")
            customer = row["customer_name"] or "未知"
            used_at = row["used_at"] or "未使用"
            output += f"- {customer}: {row['coupon_name']} [{status_name}] | 领取: {row['created_at']} | 过期: {row['expires_at']} | 使用: {used_at}\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"
