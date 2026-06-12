"""
顾客查询工具
使用 Pydantic V2 Schema 约束入参，LangChain StructuredTool 注册
"""

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class CustomerQueryInput(BaseModel):
    """顾客查询参数"""
    shop_id: int = Field(description="店铺ID")
    keyword: str = Field(description="搜索关键词（姓名或手机号）")


# ==================== Tools ====================

@tool(args_schema=CustomerQueryInput)
def query_customer(shop_id: int, keyword: str) -> str:
    """
    搜索顾客信息。
    根据姓名或手机号模糊搜索，返回顾客昵称、手机、性别。
    """
    sql = """
        SELECT
            id,
            nickname,
            phone,
            gender,
            created_at
        FROM customers
        WHERE shop_id = :shop_id
        AND (nickname LIKE :keyword OR phone LIKE :keyword)
        LIMIT 10
    """

    try:
        results = execute_sql(sql, {"shop_id": shop_id, "keyword": f"%{keyword}%"})
        if not results:
            return "未找到匹配的顾客"

        gender_map = {1: "男", 2: "女"}
        output = "查询到的顾客:\n"
        for row in results:
            nickname = row['nickname'] or "未设置"
            phone = row['phone'] or "未绑定"
            gender = gender_map.get(row["gender"], "未知")
            output += f"- {nickname} | 手机: {phone} | 性别: {gender}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"
