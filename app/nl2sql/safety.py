"""
SQL安全校验模块
防止SQL注入和危险操作
"""

import re
from app.config import settings


class SQLSafetyError(Exception):
    """SQL安全校验错误"""
    pass


def validate_sql(sql: str) -> tuple[bool, str]:
    """
    校验SQL安全性
    
    Returns:
        (is_safe, message) 元组
    """
    sql_upper = sql.upper().strip()

    # 1. 检查危险关键词（使用单词边界匹配，避免误判）
    for keyword in settings.NL2SQL_DANGEROUS_KEYWORDS:
        # 使用正则表达式匹配完整的关键词（单词边界）
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, sql_upper):
            return False, f"包含危险操作: {keyword}"

    # 2. 检查是否是SELECT语句（只允许查询）
    if not sql_upper.startswith("SELECT"):
        return False, "只允许SELECT查询语句"

    # 3. 检查是否包含子查询中的危险操作
    dangerous_patterns = [
        r"INTO\s+OUTFILE",
        r"INTO\s+DUMPFILE",
        r"LOAD_FILE",
        r"BENCHMARK",
        r"SLEEP\(",
        r"EXECUTE\s+IMMEDIATE",
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, sql_upper):
            return False, f"检测到潜在的SQL注入: {pattern}"

    # 4. 检查引号平衡
    single_quotes = sql.count("'")
    if single_quotes % 2 != 0:
        return False, "SQL引号不平衡"

    return True, "SQL校验通过"


def sanitize_sql(sql: str) -> str:
    """
    清理SQL语句
    移除多余空格、换行、markdown 代码块标记和 SQL 注释
    """
    # 移除 markdown 代码块标记
    sql = sql.strip()
    if sql.startswith("```sql"):
        sql = sql[6:]
    elif sql.startswith("```"):
        sql = sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    sql = sql.strip()
    
    # 移除 SQL 注释（单行注释 -- 和多行注释 /* */）
    sql = re.sub(r'--[^\n]*', '', sql)  # 移除单行注释
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)  # 移除多行注释
    
    # 修复双百分号问题（LLM 有时会生成 %%Y 而不是 %Y）
    sql = sql.replace('%%', '%')
    
    # 移除多余空格
    sql = re.sub(r"\s+", " ", sql).strip()
    
    # 移除末尾分号（重要！）
    while sql.endswith(";"):
        sql = sql[:-1].strip()
    
    return sql


def add_limit(sql: str, max_rows: int = None) -> str:
    """
    为SQL添加LIMIT限制
    防止返回过多数据
    """
    if max_rows is None:
        max_rows = settings.NL2SQL_MAX_ROWS

    sql_upper = sql.upper()
    if "LIMIT" not in sql_upper:
        sql = f"{sql} LIMIT {max_rows}"
    return sql


def add_shop_filter(sql: str, shop_id: int) -> str:
    """
    为SQL添加店铺过滤条件
    确保数据隔离

    安全说明：
    - shop_id 必须是 int 类型（由调用方从 auth 上下文获取）
    - 本函数使用字符串格式化插入 shop_id，因为 SQL 已由 LLM 生成
      无法直接使用参数化占位符
    - 如需更高安全等级，调用方应二次校验 shop_id 在用户权限范围内
    """
    # 强制类型校验，防止字符串注入
    if not isinstance(shop_id, int):
        try:
            shop_id = int(shop_id)
        except (ValueError, TypeError):
            raise ValueError(f"shop_id 必须是整数，收到: {type(shop_id).__name__}")
    # 检查是否已经有 shop_id 条件（支持多种格式）
    shop_id_patterns = [
        f"shop_id = {shop_id}",
        f"shop_id={shop_id}",
        f"c.shop_id = {shop_id}",
        f"p.shop_id = {shop_id}",
        f"rr.shop_id = {shop_id}",
        f"e.shop_id = {shop_id}",
        "shop_id = :shop_id",
        "shop_id = %(shop_id)s",
        "shop_id=:shop_id",
    ]
    
    has_shop_id = any(pattern in sql for pattern in shop_id_patterns)
    
    if not has_shop_id:
        # 检测是否是子查询（FROM 后面有括号）
        is_subquery = bool(re.search(r'FROM\s*\(', sql, re.IGNORECASE))
        
        if is_subquery:
            # 子查询：在 WHERE 中添加 shop_id（不带表别名）
            if "WHERE" in sql.upper():
                sql = re.sub(
                    r'(WHERE)\s+',
                    f'\\1 shop_id = {shop_id} AND ',
                    sql,
                    count=1,
                    flags=re.IGNORECASE
                )
            else:
                for keyword in ["GROUP BY", "ORDER BY", "LIMIT", "HAVING"]:
                    idx = sql.upper().find(keyword)
                    if idx != -1:
                        sql = sql[:idx] + f"WHERE shop_id = {shop_id} " + sql[idx:]
                        return sql
                sql = f"{sql} WHERE shop_id = {shop_id}"
        else:
            # 主查询：使用表别名
            main_alias = _detect_main_alias(sql)
            if "WHERE" in sql.upper():
                sql = re.sub(
                    r'(WHERE)\s+',
                    f'\\1 {main_alias}.shop_id = {shop_id} AND ',
                    sql,
                    count=1,
                    flags=re.IGNORECASE
                )
            else:
                for keyword in ["GROUP BY", "ORDER BY", "LIMIT", "HAVING"]:
                    idx = sql.upper().find(keyword)
                    if idx != -1:
                        sql = sql[:idx] + f"WHERE {main_alias}.shop_id = {shop_id} " + sql[idx:]
                        return sql
                sql = f"{sql} WHERE {main_alias}.shop_id = {shop_id}"
    else:
        # 替换参数化占位符为实际值
        sql = sql.replace(":shop_id", str(shop_id))
        sql = sql.replace("%(shop_id)s", str(shop_id))
    
    return sql


def _detect_main_alias(sql: str) -> str:
    """
    检测主查询的表别名
    支持：FROM table alias, FROM table AS alias, JOIN 场景
    """
    # 匹配 FROM table_name alias 或 FROM table_name AS alias 模式
    match = re.search(r'FROM\s+(\w+)\s+(?:AS\s+)?(\w+)', sql, re.IGNORECASE)
    if match:
        table_name = match.group(1)
        alias = match.group(2)
        # 排除 SQL 关键字和子查询
        sql_keywords = [
            "WHERE", "GROUP", "ORDER", "LIMIT", "HAVING",
            "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS",
            "ON", "SET", "VALUES", "INTO", "SELECT", "UNION",
        ]
        if alias.upper() not in sql_keywords and table_name.upper() not in sql_keywords:
            return alias

    # 默认使用 p
    return "p"
