"""
Schema链接模块
将数据库表结构映射到LLM可理解的格式

优先从 data/schema/db_schema.json 读取（自动生成），
fallback 到硬编码的 SCHEMA_INFO。
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# JSON schema 文件路径
_SCHEMA_JSON_PATH = Path(__file__).parent.parent.parent / "data" / "schema" / "db_schema.json"
_schema_cache = None


def _load_schema_from_json() -> str:
    """
    从 db_schema.json 生成 LLM 可读的 schema 文本

    Returns:
        格式化的 schema 文本
    """
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache

    try:
        if not _SCHEMA_JSON_PATH.exists():
            logger.warning(f"Schema JSON 文件不存在: {_SCHEMA_JSON_PATH}")
            return ""

        with open(_SCHEMA_JSON_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)

        lines = ["## 数据库表结构（自动生成）\n"]

        for table_name, table_info in schema.get("tables", {}).items():
            columns = table_info.get("columns", [])
            dicts = table_info.get("dicts", {})

            # 收集列信息
            col_parts = []
            for col in columns:
                name = col["name"]
                col_type = col["type"]
                comment = col.get("comment", "")
                values = col.get("values", [])

                # 构建列描述
                desc = f"{name} {col_type}"
                if comment:
                    # 清理 comment，去掉前缀如 "状态: "、"类型: "
                    clean_comment = comment
                    for prefix in ["状态: ", "类型: ", "物料类型: ", "优惠类型: ", "结算方式: ", "班次: "]:
                        if clean_comment.startswith(prefix):
                            clean_comment = clean_comment[len(prefix):]
                            break
                    if values:
                        # 有值映射，格式化为 key=value 形式
                        value_parts = [f"{v['key']}={v['value']}" for v in values]
                        desc += f" ({', '.join(value_parts)})"
                    elif clean_comment:
                        desc += f" ({clean_comment})"

                col_parts.append(desc)

            lines.append(f"### {table_name}")
            lines.append(", ".join(col_parts))

            # 关联字典信息
            if dicts:
                for dict_code, dict_entries in dicts.items():
                    dict_parts = [f"{d['key']}={d['value']}" for d in dict_entries]
                    lines.append(f"  字典 {dict_code}: {', '.join(dict_parts)}")

            lines.append("")

        result = "\n".join(lines)
        _schema_cache = result
        logger.info(f"从 JSON 加载 schema 成功: {len(schema.get('tables', {}))} 张表")
        return result

    except Exception as e:
        logger.error(f"加载 schema JSON 失败: {str(e)}")
        return ""


def get_schema_info() -> str:
    """获取数据库Schema信息（优先从 JSON 文件读取）"""
    # 尝试从 JSON 文件读取
    json_schema = _load_schema_from_json()
    if json_schema:
        return json_schema

    # fallback 到硬编码
    logger.warning("JSON schema 不可用，使用硬编码 schema")
    return SCHEMA_INFO


def invalidate_schema_cache():
    """清除 schema 缓存（sync_schema 刷新后调用）"""
    global _schema_cache
    _schema_cache = None
    logger.info("Schema 缓存已清除")


def get_table_ddl(table_name: str = None) -> str:
    """
    获取表DDL语句
    可以从 schema/ 目录下的SQL文件读取
    """
    schema_file = Path("schema/database_ddl.sql")
    if schema_file.exists():
        return schema_file.read_text(encoding="utf-8")
    return get_schema_info()


# 硬编码 fallback（当 JSON 文件不可用时使用）
SCHEMA_INFO = """
## 数据库表结构说明（fallback，优先使用 JSON 自动生成的版本）

### 业务逻辑说明（重要！）
- **收入**：指已核销确认的收入，查询 `revenue_records` 表的 `amount` 字段，按 `created_at` 或 `confirmed_at` 筛选时间
- **支出**：查询 `expenses` 表的 `amount` 字段
- **购买**：指顾客购买套餐的记录（预收款），查询 `purchases` 表的 `paid_amount` 字段
- **营收/营业额**：与"收入"同义，查询 `revenue_records` 表
- **本月**：使用 WHERE YEAR(created_at) = YEAR(NOW()) AND MONTH(created_at) = MONTH(NOW())
- **退款**：查询 `refund_records` 表，status(1=处理中,2=已完成,3=已拒绝)
- **核销**：查询 `game_sessions` 表，status(1=进行中,2=已完成)

### 顾客管理表
- **customers**: id, shop_id, nickname, phone, gender(0=未知,1=男,2=女), birthday, source(渠道), tags, remark, is_deleted, created_at
- **customer_wallets**: id, shop_id, customer_id, balance(余额), total_recharged(累计充值), total_spent(累计消费), is_deleted, created_at
- **wallet_transactions**: id, wallet_id, shop_id, customer_id, type(1=充值,2=消费,3=退款,4=调整), amount, balance_after, reference_type, reference_id, remark, is_deleted, created_at
- **points_records**: id, shop_id, customer_id, type(1=获取,2=消耗,3=过期,4=调整), points, balance_after, source, reference_id, remark, is_deleted, created_at

### 交易管理表
- **purchases**: id, shop_id, customer_id, package_id, purchase_type(purchase-购买套餐,recharge-充值), channel(store/meituan/douyin/other), third_party_coupon_code, coupon_usage_id, start_date, total_amount, paid_amount, coupon_discount, payment_method, status(1=有效,2=已退款,3=已过期), operator_staff_id, remark, is_deleted, created_at, updated_at
- **prepayments**: id, shop_id, purchase_id, amount, balance_before, balance_after, is_deleted, created_at
- **customer_sessions**: id, shop_id, customer_id, purchase_id, session_date, status(1=可用,2=已核销,3=已过期,4=已退款), is_deleted
- **game_sessions**: id, shop_id, customer_id, customer_session_id, staff_id, start_time, end_time, status(1=进行中,2=已完成), is_deleted
- **revenue_records**: id, shop_id, game_session_id, purchase_id, amount, confirmed_at, confirmed_by(确认收入员工ID), customer_id, payment_method, is_deleted, created_at
- **refund_records**: id, shop_id, purchase_id, refund_amount, reason, deducted_amount(扣除金额), refund_prepay_amount(退还预收款), refund_wallet_amount(退还钱包), refunded_sessions(退款次数), status(1=处理中,2=已完成,3=已拒绝), operated_by, revenue_id, is_deleted, created_at, updated_at

### 套餐管理表
- **packages**: id, shop_id, name, type(varchar: SINGLE/WEEKLY/MONTHLY), duration_minutes, price, original_price(原价), max_people_per_session(每场上限人数), description, image, is_active, is_deleted, created_at, updated_at
- **package_bom**: id, package_id, material_id, quantity, is_deleted, created_at

### 库存管理表
- **materials**: id, shop_id, name, sku, category, unit, type(1=消耗品,2=工具), min_stock(最低库存预警), is_deleted, created_at
- **inventory**: id, shop_id, material_id, quantity
- **inventory_transactions**: id, shop_id, material_id, type(1=入库,2=出库), quantity, reference_type, reference_id, operator_staff_id, remark, is_deleted, created_at
- **suppliers**: id, shop_id, name, contact_person, phone, address, remark, is_deleted, created_at
- **purchase_orders**: id, shop_id, supplier_id, order_number, order_date, type(1=现结,2=赊账), total_amount, paid_amount, status(1=待付款,2=部分付款,3=已完成), operator_staff_id, remark, is_deleted, created_at, updated_at
- **purchase_order_items**: id, purchase_order_id, material_id, quantity, unit_price, is_deleted, created_at
- **purchase_payments**: id, purchase_order_id, amount, payment_method, paid_at, remark, expense_id, is_deleted, created_at

### 财务管理表
- **expenses**: id, shop_id, category_id, amount, payment_method, expense_date, remark, is_deleted, created_at
- **expense_categories**: id, shop_id, name, sort, is_deleted, created_at
- **invoices**: id, shop_id, reference_type, reference_id, invoice_number, amount, issued_at, is_deleted, created_at
- **commission_rules**: id, shop_id, role_id, rule_type(1=按次,2=按流水比例,3=固定金额), value, description, is_active, is_deleted, created_at
- **commission_settlements**: id, shop_id, staff_id, settlement_period, total_amount, status(1=待结算,2=已发放), operated_by, is_deleted, created_at, updated_at
- **daily_snapshots**: id, shop_id, snapshot_date, sales_total, revenue_confirmed, new_customers, active_sessions, average_duration(平均时长-分钟), inventory_warns(库存预警数), created_at

### 营销管理表
- **coupons**: id, shop_id, name, type(1=固定金额,2=百分比,3=兑换券), value, min_order_amount, total_stock, remain_stock, valid_days, is_active, is_deleted, created_at
- **coupon_usages**: id, coupon_id, customer_id, status(1=未使用,2=已使用,3=已过期), used_at, expires_at, is_deleted, created_at
- **coupon_verification_logs**: id, shop_id, coupon_usage_id, channel, operation, result, verified_at, created_at

### 内容管理表
- **articles**: id, shop_id, category_id, title, content, content_type(1=图片,2=视频,3=富文本,4=纯文本), cover_image, is_published, published_at, is_deleted, created_at, updated_at
- **article_categories**: id, shop_id, name, sort, is_deleted, created_at
- **shop_faqs**: id, shop_id, question, answer, category, sort_order, is_active, created_at, updated_at

### 员工管理表
- **staff**: id, boss_status(0=员工,1=商户), name, phone, contact_email, id_card, avatar, employment_type(1=全职,2=兼职), max_seats, used_seats, remark, status(1=在职,0=离职), is_ban, is_deleted, created_at, updated_at
- **staff_accounts**: id, staff_id, username, password_hash, wechat_openid, last_login_at, is_deleted, created_at
- **staff_roles**: staff_id, role_id
- **staff_shops**: id, staff_id, shop_id, created_at
- **staff_schedules**: id, shop_id, staff_id, schedule_date, start_time, end_time, type(1=上班,2=休息), remark, created_at
- **attendance_records**: id, shop_id, staff_id, check_in_time, check_out_time, date, status(1=正常,2=迟到,3=早退,4=加班), is_deleted, created_at

### 权限管理表
- **roles**: id, shop_id, name, description, created_at
- **permissions**: id, parent_id, name, menu_code, path, component, redirect, icon, sort, type(1=目录,2=菜单,3=按钮), description, is_active, is_deleted, super_admin_visible, created_at, updated_at
- **role_permissions**: role_id, permission_id

### 店铺与席位表
- **shops**: id, owner_staff_id, seat_id, name, address, contact_phone, max_capacity, status(1=营业,2=休息,3=停业), description, open_time, close_time, business_days, sign_photo, logo, mp_qrcode_path, is_deleted, created_at, updated_at
- **seat_subscriptions**: id, seat_no, staff_id, start_date, end_date, status(1=有效,2=已过期,3=已取消), remark, created_at, updated_at
- **seat_subscriptions_transactions**: id, seat_id, amount, payment_method, payment_no, subscription_type(1=月付,2=年付), subscription_num, status(1=有效,2=已退款), refund_amount, refund_days, created_at

### 其他表
- **feedbacks**: id, shop_id, customer_id, game_session_id, feedback_type(1=满意度,2=建议,3=投诉,4=其他), rating, content, status(1=待处理,2=已回复,3=已关闭), reply_content, is_deleted, created_at
- **notification_logs**: id, shop_id, recipient_type(1=顾客,2=员工), recipient_id, channel(1=短信,2=邮件,3=站内信,4=微信), title, content, status(1=未读,2=已读), error_message, sent_at, created_at
- **queue_entries**: id, shop_id, customer_id, queue_number, party_size, status(1=排队中,2=已入座,3=已取消,4=已通知), requested_at, seated_at, notified_at, remark, is_deleted, created_at
- **operation_logs**: id, shop_id, operator_type(1=员工,2=顾客), operator_id, action, target_type, target_id, detail(json), ip_address, created_at
- **sys_dicts**: id, dict_code, dict_key, dict_value, dict_label, sort, is_active, shop_id, created_at, updated_at
"""
