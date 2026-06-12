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

    # 1. 检查危险关键词
    for keyword in settings.NL2SQL_DANGLED_KEYWORDS:
        if keyword in sql_upper:
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
    
    注意：
    - 主查询使用表别名（如 p.shop_id）
    - 子查询中使用 shop_id（不带表别名）
    """
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
    通常是 FROM 后面的第一个别名
    """
    # 匹配 FROM table_name alias 模式
    match = re.search(r'FROM\s+\w+\s+(\w+)', sql, re.IGNORECASE)
    if match:
        alias = match.group(1)
        # 排除 SQL 关键字
        sql_keywords = ["WHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "JOIN", "LEFT", "RIGHT", "INNER", "ON"]
        if alias.upper() not in sql_keywords:
            return alias
    
    # 默认使用 p
    return "p"
