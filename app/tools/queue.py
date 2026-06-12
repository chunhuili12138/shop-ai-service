"""
排队管理工具
查询当前座位占用情况
"""

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class ActiveSessionsInput(BaseModel):
    """当前游玩Session查询参数"""
    shop_id: int = Field(description="店铺ID")


# ==================== Tools ====================

@tool(args_schema=ActiveSessionsInput)
def query_active_sessions(shop_id: int) -> str:
    """
    查询当前正在进行的游玩Session。
    返回：当前有多少客人在玩、顾客昵称、套餐名称、开始时间、已玩时长。
    用于了解当前店铺的座位占用情况。
    """
    sql = """
        SELECT
            gs.id as session_id,
            c.nickname as customer_name,
            p.name as package_name,
            gs.start_time,
            TIMESTAMPDIFF(MINUTE, gs.start_time, NOW()) as duration_minutes
        FROM game_sessions gs
        LEFT JOIN customer_sessions cs ON gs.customer_session_id = cs.id
        LEFT JOIN purchases pu ON cs.purchase_id = pu.id
        LEFT JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        WHERE gs.shop_id = :shop_id
        AND gs.status = 1
        ORDER BY gs.start_time DESC
    """

    try:
        results = execute_sql(sql, {"shop_id": shop_id})

        if not results:
            return "当前没有客人在游玩"

        output = f"当前有 {len(results)} 位客人在游玩：\n"
        for i, row in enumerate(results, 1):
            customer = row.get("customer_name", "未知")
            package = row.get("package_name", "未知")
            start_time = row.get("start_time", "未知")
            duration = row.get("duration_minutes", 0)

            # 格式化时长
            if duration >= 60:
                hours = duration // 60
                mins = duration % 60
                duration_str = f"{hours}小时{mins}分钟"
            else:
                duration_str = f"{duration}分钟"

            output += f"{i}. {customer} - {package} | 开始: {start_time} | 已玩: {duration_str}\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"
