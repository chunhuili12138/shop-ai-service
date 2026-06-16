"""
数据库 Schema 同步脚本
从 INFORMATION_SCHEMA + sys_dicts 读取真实表结构，生成 JSON schema 文件

可独立运行：python scripts/sync_schema.py
也可被定时任务调用：from scripts.sync_schema import sync_schema; sync_schema()
"""

import json
import os
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_db_connection():
    """获取数据库连接"""
    from app.config import settings
    import pymysql
    return pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def sync_schema(output_path: str = None) -> dict:
    """
    从数据库读取完整 schema 并写入 JSON 文件

    Args:
        output_path: 输出文件路径，默认 data/schema/db_schema.json

    Returns:
        生成的 schema 字典
    """
    if output_path is None:
        output_path = os.path.join(os.path.dirname(__file__), "..", "data", "schema", "db_schema.json")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. 读取所有表的列信息
        cursor.execute("""
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_TYPE,
                   IS_NULLABLE, COLUMN_KEY, COLUMN_COMMENT, COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """)
        columns = cursor.fetchall()

        # 2. 读取字典数据（状态映射）
        cursor.execute("""
            SELECT dict_code, dict_key, dict_label, dict_value
            FROM sys_dicts
            WHERE is_active = 1
            ORDER BY dict_code, dict_key
        """)
        dicts = cursor.fetchall()

        # 3. 按表名分组
        tables = {}
        for col in columns:
            table_name = col["TABLE_NAME"]
            if table_name not in tables:
                tables[table_name] = {"columns": [], "dicts": {}}

            # 解析 COMMENT 中的状态映射
            comment = col["COLUMN_COMMENT"] or ""
            values = _parse_status_values(comment, col["DATA_TYPE"])

            column_info = {
                "name": col["COLUMN_NAME"],
                "type": col["DATA_TYPE"],
                "column_type": col["COLUMN_TYPE"],
                "nullable": col["IS_NULLABLE"] == "YES",
                "key": col["COLUMN_KEY"] or "",
                "comment": comment,
                "default": col["COLUMN_DEFAULT"],
            }
            if values:
                column_info["values"] = values

            tables[table_name]["columns"].append(column_info)

        # 4. 关联字典数据到表
        # 构建 dict_code → 表名的映射（如 refund_status → refund_records）
        dict_table_map = _build_dict_table_map(dicts, tables)

        for d in dicts:
            dict_code = d["dict_code"]
            table_name = dict_table_map.get(dict_code)
            if table_name and table_name in tables:
                if dict_code not in tables[table_name]["dicts"]:
                    tables[table_name]["dicts"][dict_code] = []
                tables[table_name]["dicts"][dict_code].append({
                    "key": d["dict_key"],
                    "label": d["dict_label"],
                    "value": d["dict_value"],
                })

        # 5. 生成最终 schema
        schema = {
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "database": conn.db.decode() if isinstance(conn.db, bytes) else str(conn.db),
            "tables": tables,
        }

        # 6. 写入文件
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)

        print(f"[SchemaSync] 生成完成: {output_path} ({len(tables)} 张表)")
        return schema

    finally:
        conn.close()


def _parse_status_values(comment: str, data_type: str) -> list:
    """
    从 COMMENT 中解析状态值映射

    支持格式：
    - "状态: 1-处理中, 2-已完成, 3-已拒绝"
    - "状态: 1-排队中 2-已入座 3-已取消 4-已通知"
    - "0-正常，1-已删除"
    - "类型: 1-消耗品, 2-工具"
    """
    if not comment:
        return []

    import re
    # 匹配 "数字-文字" 模式
    pattern = r'(\d+)\s*[-:：]\s*([^\s,，、]+)'
    matches = re.findall(pattern, comment)

    if len(matches) < 2:
        return []

    values = []
    for key, value in matches:
        values.append({"key": int(key), "value": value})

    return values


def _build_dict_table_map(dicts: list, tables: dict) -> dict:
    """
    构建 dict_code → table_name 的映射

    规则：dict_code 去掉 _status/_type 后缀，匹配表名
    如：refund_status → refund_records, order_status → purchases
    """
    mapping = {}

    # 已知映射（手动维护，因为有些 dict_code 和表名不完全对应）
    known_mappings = {
        "refund_status": "refund_records",
        "order_status": "purchases",
        "game_status": "game_sessions",
        "customer_session_status": "customer_sessions",
        "feedback_status": "feedbacks",
        "notify_status": "notification_logs",
        "attendance_status": "attendance_records",
        "settlement_status": "commission_settlements",
        "po_status": "purchase_orders",
        "queue_status": "queue_entries",
        "merchant_status": "staff",
        "coupon_usage_status": "coupon_usages",
        "subscription_status": "seat_subscriptions",
        "wallet_tx_type": "wallet_transactions",
    }

    for d in dicts:
        dict_code = d["dict_code"]
        if dict_code in known_mappings:
            mapping[dict_code] = known_mappings[dict_code]
        else:
            # 尝试自动匹配：去掉 _status/_type 后缀
            base = dict_code.replace("_status", "").replace("_type", "")
            for table_name in tables:
                if base in table_name:
                    mapping[dict_code] = table_name
                    break

    return mapping


if __name__ == "__main__":
    sync_schema()
