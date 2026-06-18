"""
优惠券管理工具
查询优惠券、发放优惠券（HITL）、查询使用记录

状态映射：coupon_usage_status: 1=未使用, 2=已使用, 3=已过期
"""

import json
from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql, get_engine


class CouponsQueryInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    status: Optional[str] = Field(default=None, description="状态: active=启用, disabled=禁用")

class GrantCouponInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    coupon_id: Optional[int] = Field(default=None, description="优惠券ID（缺失时展示优惠券选择列表）")
    customer_ids: Optional[str] = Field(default=None, description="顾客ID列表，逗号分隔（缺失时展示顾客选择列表）")

class CouponUsagesQueryInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    customer_id: Optional[int] = Field(default=None, description="顾客ID（可选）")
    limit: int = Field(default=10, description="返回数量")


@tool(args_schema=CouponsQueryInput)
def query_coupons(shop_id: int, status: Optional[str] = None) -> str:
    """
    查询店铺优惠券列表。
    支持按状态筛选（active=启用, disabled=禁用），返回优惠券名称、类型、面值、库存、有效期等信息。
    """
    sql = """
        SELECT id, name, type, value, min_order_amount, total_stock,
               remain_stock, valid_days, is_active, created_at
        FROM coupons WHERE shop_id = :shop_id
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
            tn = type_names.get(row["type"], "未知")
            sn = status_names.get(row["is_active"], "未知")
            if row["type"] == 1:
                vs = f"¥{row['value']}"
            elif row["type"] == 2:
                vs = f"{row['value']}%"
            else:
                vs = "兑换券"
            output += f"- [{row['id']}] {row['name']} ({tn}): {vs} | 库存: {row['remain_stock']}/{row['total_stock']} | 有效期: {row['valid_days']}天 [{sn}]\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=GrantCouponInput)
def grant_coupon(shop_id: int, coupon_id: Optional[int] = None, customer_ids: Optional[str] = None) -> dict:
    """发放优惠券给顾客。返回确认框，需用户确认后执行。"""
    try:
        fields = []

        # ===== 检查 coupon_id =====
        coupon_info = None
        if not coupon_id or coupon_id == 0:
            available = execute_sql(
                "SELECT id, name, type, value, remain_stock, valid_days "
                "FROM coupons WHERE shop_id = :sid AND is_active = 1 AND is_deleted = 0 "
                "ORDER BY created_at DESC",
                {"sid": shop_id}
            )
            if not available:
                return {"type": "error", "message": "当前没有可用的优惠券"}
            fields.append({
                "name": "coupon_id",
                "type": "select",
                "label": "选择优惠券",
                "required": True,
                "options": [
                    {"value": c["id"], "label": f"{c['name']} (¥{c['value']}, 库存{c['remain_stock']})"}
                    for c in available
                ],
            })
        else:
            # coupon_id 已提供，查询确认
            coupon_info = execute_sql(
                "SELECT id, name, remain_stock, valid_days, is_active "
                "FROM coupons WHERE shop_id = :sid AND id = :cid",
                {"sid": shop_id, "cid": coupon_id}
            )
            if not coupon_info:
                return {"type": "error", "message": f"优惠券 ID {coupon_id} 不存在"}
            if coupon_info[0]["is_active"] != 1:
                return {"type": "error", "message": "该优惠券已禁用"}

        # ===== 检查 customer_ids =====
        if not customer_ids or customer_ids.strip() == "":
            customers = execute_sql(
                "SELECT id, nickname, phone FROM customers "
                "WHERE shop_id = :sid AND is_deleted = 0 ORDER BY nickname",
                {"sid": shop_id}
            )
            if not customers:
                return {"type": "error", "message": "当前没有顾客"}
            fields.append({
                "name": "customer_ids",
                "type": "multi_select",
                "label": "选择顾客",
                "required": True,
                "options": [
                    {"value": "ALL", "label": f"所有顾客（{len(customers)}人）"},
                ] + [
                    {"value": str(c["id"]), "label": f"{c['nickname']} ({c['phone'] or '无手机'})"}
                    for c in customers
                ],
            })

        # ===== 有缺失字段 → 返回填写表单 =====
        if fields:
            # 构建已有信息的 details
            details = {}
            if coupon_info:
                details["优惠券"] = coupon_info[0]["name"]
                details["库存"] = str(coupon_info[0]["remain_stock"])
                details["有效期"] = f"{coupon_info[0]['valid_days']}天"
            return {
                "type": "confirm",
                "tool_name": "grant_coupon",
                "title": "发放优惠券",
                "message": "请填写以下信息：",
                "details": details,
                "fields": fields,
                "buttons": [
                    {"type": "confirm", "label": "确认发放"},
                    {"type": "cancel", "label": "取消"},
                ],
                "action": "grant_coupon",
                "params": {"shop_id": shop_id, **({"coupon_id": coupon_id} if coupon_id else {}), **({"customer_ids": customer_ids} if customer_ids else {})},
            }

        # ===== 参数齐全，执行验证 =====
        coupon = coupon_info[0]

        if customer_ids.upper() == "ALL":
            all_customers = execute_sql(
                "SELECT GROUP_CONCAT(id) as ids FROM customers WHERE shop_id = :sid AND is_deleted = 0",
                {"sid": shop_id}
            )
            customer_ids = str(all_customers[0]["ids"]) if all_customers and all_customers[0]["ids"] else ""

        id_list = [int(i.strip()) for i in customer_ids.split(",") if i.strip()]
        if not id_list:
            return {"type": "error", "message": "请提供有效的顾客ID"}
        if coupon["remain_stock"] < len(id_list):
            return {"type": "error", "message": f"库存不足，当前: {coupon['remain_stock']}，需要: {len(id_list)}"}

        # 检查重复领取
        placeholders = ", ".join([str(i) for i in id_list])
        dup_sql = f"""
            SELECT customer_id FROM coupon_usages
            WHERE coupon_id = :coupon_id AND customer_id IN ({placeholders}) AND status != 3
        """
        dup_results = execute_sql(dup_sql, {"coupon_id": coupon_id})
        if dup_results:
            dup_ids = [r["customer_id"] for r in dup_results]
            return {"type": "error", "message": f"顾客 {dup_ids} 已领取过该优惠券"}

        return {
            "type": "confirm",
            "tool_name": "grant_coupon",
            "title": "确认发放优惠券",
            "message": f"确定要将「{coupon['name']}」发放给 {len(id_list)} 位顾客吗？",
            "details": {
                "优惠券": coupon["name"],
                "发放人数": str(len(id_list)),
                "当前库存": str(coupon["remain_stock"]),
                "有效期": f"{coupon['valid_days']}天"
            },
            "fields": [],
            "buttons": [
                {"type": "confirm", "label": "确认发放"},
                {"type": "cancel", "label": "取消"}
            ],
            "action": "grant_coupon",
            "params": {"shop_id": shop_id, "coupon_id": coupon_id, "customer_ids": customer_ids}
        }
    except Exception as e:
        return {"type": "error", "message": f"查询失败: {str(e)}"}


def execute_grant_coupon(shop_id: int, coupon_id: int, customer_ids: str, operator_id: Optional[int] = None) -> str:
    """执行发放优惠券（事务）"""
    engine = get_engine()
    try:
        id_list = [int(i.strip()) for i in customer_ids.split(",") if i.strip()]
        if not id_list:
            return "请提供有效的顾客ID"
        with engine.begin() as conn:
            from sqlalchemy import text
            # 锁定优惠券行
            coupon = conn.execute(text(
                "SELECT id, name, remain_stock, valid_days FROM coupons WHERE id = :cid AND shop_id = :sid FOR UPDATE"
            ), {"cid": coupon_id, "sid": shop_id}).fetchone()
            if not coupon:
                return "优惠券不存在"
            if coupon[2] < len(id_list):
                return f"库存不足，当前: {coupon[2]}，需要: {len(id_list)}"
            # 批量插入
            success = 0
            for cid in id_list:
                try:
                    conn.execute(text(
                        "INSERT INTO coupon_usages (coupon_id, customer_id, status, expires_at, created_at) "
                        "VALUES (:coupon_id, :customer_id, 1, DATE_ADD(NOW(), INTERVAL :valid_days DAY), NOW())"
                    ), {"coupon_id": coupon_id, "customer_id": cid, "valid_days": coupon[3]})
                    success += 1
                except Exception:
                    pass
            # 更新库存
            if success > 0:
                conn.execute(text(
                    "UPDATE coupons SET remain_stock = remain_stock - :cnt WHERE id = :cid"
                ), {"cnt": success, "cid": coupon_id})
        return f"发放完成: 成功 {success} 张"
    except Exception as e:
        return f"发放失败: {str(e)}"


@tool(args_schema=CouponUsagesQueryInput)
def query_coupon_usages(shop_id: int, customer_id: Optional[int] = None, limit: int = 10) -> str:
    """
    查询优惠券使用记录。
    支持按顾客ID筛选，返回顾客昵称、优惠券名称、状态（未使用/已使用/已过期）、领取时间、过期时间。
    """
    sql = """
        SELECT cu.id, c.nickname as customer_name, cp.name as coupon_name,
               cu.status, cu.used_at, cu.expires_at, cu.created_at
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
            sn = status_names.get(row["status"], "未知")
            c = row["customer_name"] or "未知"
            ua = row["used_at"] or "未使用"
            output += f"- {c}: {row['coupon_name']} [{sn}] | 领取: {row['created_at']} | 过期: {row['expires_at']} | 使用: {ua}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"
