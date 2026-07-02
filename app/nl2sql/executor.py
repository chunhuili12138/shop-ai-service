"""
SQL执行器
安全执行SQL并返回结果
"""

import threading
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from app.config import settings


# 创建数据库连接池
_engine = None
_engine_lock = threading.Lock()


def get_engine():
    """获取数据库引擎单例（双重检查锁定，线程安全）"""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = create_engine(
                    settings.MYSQL_URL,
                    poolclass=QueuePool,
                    pool_size=5,
                    max_overflow=10,
                    pool_timeout=30,
                )
    return _engine


def execute_sql(sql: str, params: dict = None) -> list[dict]:
    """
    安全执行SQL查询
    
    Args:
        sql: SQL语句
        params: 参数字典
    
    Returns:
        查询结果列表
    """
    try:
        with get_engine().connect() as conn:
            result = conn.execute(text(sql), params or {})
            columns = result.keys()
            rows = result.fetchall()
            return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        raise Exception(f"SQL执行失败: {str(e)}")


def execute_sql_with_retry(sql: str, params: dict = None, max_retries: int = 2) -> list[dict]:
    """
    带重试的SQL执行
    用于Self-Correction场景
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return execute_sql(sql, params)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                # 记录错误，供LLM修正
                continue
    raise last_error


def format_results_for_llm(results: list[dict]) -> str:
    """将查询结果格式化为LLM可理解的格式"""
    if not results:
        return "查询成功，但没有符合条件的数据记录。请告诉用户：当前没有找到相关数据。"

    # 表头
    columns = list(results[0].keys())
    header = " | ".join(columns)
    separator = " | ".join(["---"] * len(columns))

    # 数据行
    rows = []
    for row in results[:20]:  # 最多显示20行
        row_str = " | ".join([str(v) if v is not None else "NULL" for v in row.values()])
        rows.append(row_str)

    return f"查询成功，共 {len(results)} 条记录：\n{header}\n{separator}\n" + "\n".join(rows)
