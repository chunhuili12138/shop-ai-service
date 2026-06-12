"""
评价反馈工具
查询评价列表、回复评价
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class FeedbacksQueryInput(BaseModel):
    """评价查询参数"""
    shop_id: int = Field(description="店铺ID")
    status: Optional[str] = Field(
        default=None,
        description="状态筛选: pending=待处理, replied=已回复（可选）"
    )
    limit: int = Field(default=10, description="返回数量，默认10")


class ReplyFeedbackInput(BaseModel):
    """回复评价参数"""
    shop_id: int = Field(description="店铺ID")
    feedback_id: int = Field(description="评价ID")
    reply_content: str = Field(description="回复内容")


# ==================== Tools ====================

@tool(args_schema=FeedbacksQueryInput)
def query_feedbacks(shop_id: int, status: Optional[str] = None, limit: int = 10) -> str:
    """
    查询顾客评价列表。
    返回顾客姓名、评价类型、评分、内容、状态、时间。
    """
    sql = """
        SELECT
            f.id,
            c.nickname as customer_name,
            f.feedback_type,
            f.rating,
            f.content,
            f.reply_content,
            f.status,
            f.created_at
        FROM feedbacks f
        LEFT JOIN game_sessions gs ON f.game_session_id = gs.id
        LEFT JOIN customer_sessions cs ON gs.customer_session_id = cs.id
        LEFT JOIN purchases pu ON cs.purchase_id = pu.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        WHERE f.shop_id = :shop_id
    """

    params = {"shop_id": shop_id, "limit": limit}

    if status:
        if status == "pending":
            sql += " AND f.status = 0"
        elif status == "replied":
            sql += " AND f.status = 1"

    sql += " ORDER BY f.created_at DESC LIMIT :limit"

    try:
        results = execute_sql(sql, params)

        if not results:
            return "暂无评价"

        type_names = {1: "满意度", 2: "建议", 3: "投诉", 4: "其他"}
        status_names = {0: "待处理", 1: "已回复"}

        output = "评价列表:\n"
        for row in results:
            type_name = type_names.get(row["feedback_type"], "未知")
            status_name = status_names.get(row["status"], "未知")
            customer = row["customer_name"] or "匿名"
            rating = "⭐" * row["rating"] if row["rating"] else "未评分"
            content = row["content"][:50] + "..." if row.get("content") and len(row["content"]) > 50 else row.get("content", "")

            output += f"- [{row['id']}] {customer} ({type_name}): {rating}\n"
            output += f"  内容: {content}\n"
            if row.get("reply_content"):
                output += f"  回复: {row['reply_content'][:50]}\n"
            output += f"  状态: {status_name} | 时间: {row['created_at']}\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=ReplyFeedbackInput)
def reply_feedback(shop_id: int, feedback_id: int, reply_content: str) -> str:
    """
    回复顾客评价。
    更新评价状态为已回复，并记录回复内容。
    """
    # 先查询评价是否存在
    check_sql = """
        SELECT id, status
        FROM feedbacks
        WHERE shop_id = :shop_id AND id = :feedback_id
    """

    try:
        check_results = execute_sql(check_sql, {"shop_id": shop_id, "feedback_id": feedback_id})

        if not check_results:
            return "评价不存在"

        feedback = check_results[0]

        if feedback["status"] == 1:
            return "该评价已回复，无需重复回复"

        # 更新评价
        update_sql = """
            UPDATE feedbacks
            SET reply_content = :reply_content, status = 1
            WHERE id = :feedback_id
        """

        execute_sql(update_sql, {
            "reply_content": reply_content,
            "feedback_id": feedback_id
        })

        return f"回复成功: {reply_content}"

    except Exception as e:
        return f"回复失败: {str(e)}"
