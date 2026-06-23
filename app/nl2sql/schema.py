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

### 核心表
- **customers**: id, shop_id, nickname, phone, gender, birthday, source, tags, remark, is_deleted, created_at
- **purchases**: id, shop_id, customer_id, package_id, channel, total_amount, paid_amount, payment_method, status(1=有效,2=已退款,3=已过期), is_deleted, created_at
- **revenue_records**: id, shop_id, game_session_id, purchase_id, amount, confirmed_at, confirmed_by, customer_id, payment_method, is_deleted, created_at（收入确认记录，核销后生成）
- **refund_records**: id, shop_id, purchase_id, refund_amount, reason, deducted_amount, status(1=处理中,2=已完成,3=已拒绝), is_deleted, created_at
- **customer_sessions**: id, shop_id, customer_id, purchase_id, session_date, status(1=可用,2=已核销,3=已过期,4=已退款), is_deleted
- **game_sessions**: id, shop_id, customer_id, customer_session_id, staff_id, start_time, end_time, status(1=进行中,2=已完成), is_deleted
- **packages**: id, shop_id, name, type(varchar: SINGLE/WEEKLY/MONTHLY), duration_minutes, price, is_active, is_deleted
- **feedbacks**: id, shop_id, customer_id, game_session_id, feedback_type, rating, content, status(1=待处理,2=已回复,3=已关闭), reply_content, is_deleted
- **notification_logs**: id, shop_id, recipient_type, recipient_id, channel, title, content, status(1=未读,2=已读)
- **expenses**: id, shop_id, category_id, amount, payment_method, expense_date, remark, is_deleted
- **materials**: id, shop_id, name, sku, category, unit, type(1=消耗品,2=工具), min_stock, is_deleted
- **inventory**: id, shop_id, material_id, quantity
- **staff**: id, name, phone, status(1=在职,0=离职), boss_status, is_deleted
- **staff_schedules**: id, shop_id, staff_id, schedule_date, start_time, end_time, type(1=上班,2=休息)
- **attendance_records**: id, shop_id, staff_id, check_in_time, check_out_time, date, status(1=正常,2=迟到,3=早退,4=加班)
- **daily_snapshots**: id, shop_id, snapshot_date, sales_total, revenue_confirmed, new_customers, active_sessions, average_duration
- **coupons**: id, shop_id, name, type(1=固定金额,2=百分比,3=兑换券), value, total_stock, remain_stock, is_active
- **coupon_usages**: id, coupon_id, customer_id, status(1=未使用,2=已使用,3=已过期), expires_at
- **queue_entries**: id, shop_id, customer_id, queue_number, status(1=排队中,2=已入座,3=已取消,4=已通知)
- **operation_logs**: id, shop_id, operator_id, action, target_type, target_id, detail, created_at
"""
