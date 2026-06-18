"""
评价反馈工具
查询评价列表、回复评价（HITL）

状态映射：feedback_status: 1=待处理, 2=已回复, 3=已关闭
"""

import json
from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql, get_engine


class FeedbacksQueryInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    status: Optional[str] = Field(default=None, description="状态: pending=待处理, replied=已回复")
    limit: int = Field(default=10, description="返回数量")

class ReplyFeedbackInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    feedback_id: int = Field(description="评价ID")
    reply_content: Optional[str] = Field(default=None, description="回复内容")


@tool(args_schema=FeedbacksQueryInput)
def query_feedbacks(shop_id: int, status: Optional[str] = None, limit: int = 10) -> str:
    """
    查询顾客评价列表。
    支持按状态筛选（pending=待处理, replied=已回复），返回顾客昵称、评分、评价内容、回复状态。
    """
    sql = """
        SELECT f.id, c.nickname as customer_name, f.feedback_type,
               f.rating, f.content, f.reply_content, f.status, f.created_at
        FROM feedbacks f
        LEFT JOIN customers c ON f.customer_id = c.id
        WHERE f.shop_id = :shop_id AND (f.is_deleted = 0 OR f.is_deleted IS NULL)
    """
    params = {"shop_id": shop_id, "limit": limit}
    if status:
        if status == "pending":
            sql += " AND f.status = 1"
        elif status == "replied":
            sql += " AND f.status = 2"
    sql += " ORDER BY f.created_at DESC LIMIT :limit"
    try:
        results = execute_sql(sql, params)
        if not results:
            return "暂无评价"
        type_names = {1: "满意度", 2: "建议", 3: "投诉", 4: "其他"}
        status_names = {1: "待处理", 2: "已回复", 3: "已关闭"}
        output = "评价列表:\n"
        for row in results:
            tn = type_names.get(row["feedback_type"], "未知")
            sn = status_names.get(row["status"], "未知")
            c = row["customer_name"] or "匿名"
            r = "⭐" * row["rating"] if row["rating"] else "未评分"
            content = (row["content"] or "")[:50]
            output += f"- [{row['id']}] {c} ({tn}): {r}\n"
            output += f"  内容: {content}\n"
            if row.get("reply_content"):
                output += f"  回复: {row['reply_content'][:50]}\n"
            output += f"  状态: {sn} | 时间: {row['created_at']}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=ReplyFeedbackInput)
def reply_feedback(shop_id: int, feedback_id: int, reply_content: Optional[str] = None) -> dict:
    """回复顾客评价。返回确认框，需用户确认后执行。"""
    try:
        # ===== 参数完整性检查 =====
        if not feedback_id or feedback_id == 0:
            # 查询待处理评价
            pending = execute_sql(
                "SELECT f.id, c.nickname, f.rating, f.content, f.feedback_type "
                "FROM feedbacks f "
                "LEFT JOIN customers c ON f.customer_id = c.id "
                "WHERE f.shop_id = :sid AND f.status = 1 AND (f.is_deleted = 0 OR f.is_deleted IS NULL) "
                "ORDER BY f.created_at DESC",
                {"sid": shop_id}
            )
            if not pending:
                return {"type": "error", "message": "当前没有待处理的评价"}
            return {
                "type": "confirm",
                "tool_name": "reply_feedback",
                "title": "回复评价",
                "message": "请选择要回复的评价：",
                "details": {},
                "fields": [
                    {
                        "name": "feedback_id",
                        "type": "select",
                        "label": "选择评价",
                        "required": True,
                        "options": [
                            {"value": str(f["id"]), "label": f"{f['nickname'] or '匿名'} - {'⭐' * f['rating'] if f['rating'] else '未评分'} {(f['content'] or '')[:30]}"}
                            for f in pending
                        ],
                    },
                    {"name": "reply_content", "type": "textarea", "label": "回复内容", "required": True, "placeholder": "请输入回复内容", "value": reply_content or ""},
                ],
                "buttons": [
                    {"type": "confirm", "label": "确认回复"},
                    {"type": "cancel", "label": "取消"},
                ],
                "action": "reply_feedback",
                "params": {"shop_id": shop_id},
            }

        # ===== 参数齐全 =====
        check_sql = """
            SELECT id, status, content FROM feedbacks
            WHERE shop_id = :shop_id AND id = :feedback_id
        """
        check_results = execute_sql(check_sql, {"shop_id": shop_id, "feedback_id": feedback_id})
        if not check_results:
            return {"type": "error", "message": "评价不存在"}
        fb = check_results[0]
        if fb["status"] == 2:
            return {"type": "error", "message": "该评价已回复"}
        if fb["status"] == 3:
            return {"type": "error", "message": "该评价已关闭"}
        return {
            "type": "confirm",
            "tool_name": "reply_feedback",
            "title": "确认回复评价",
            "message": f"确定要回复这条评价吗？",
            "details": {
                "评价内容": (fb["content"] or "")[:100],
            },
            "fields": [
                {"name": "reply_content", "type": "textarea", "label": "回复内容", "required": True, "placeholder": "请输入回复内容", "value": reply_content or ""}
            ],
            "buttons": [
                {"type": "confirm", "label": "确认回复"},
                {"type": "cancel", "label": "取消"}
            ],
            "action": "reply_feedback",
            "params": {"shop_id": shop_id, "feedback_id": feedback_id}
        }
    except Exception as e:
        return {"type": "error", "message": f"查询失败: {str(e)}"}


def execute_reply_feedback(shop_id: int, feedback_id: int, reply_content: str, operator_id: Optional[int] = None) -> str:
    """执行回复评价（事务）"""
    engine = get_engine()
    try:
        with engine.begin() as conn:
            from sqlalchemy import text
            check = conn.execute(text(
                "SELECT id, status FROM feedbacks WHERE id = :fid AND shop_id = :sid AND (is_deleted = 0 OR is_deleted IS NULL) FOR UPDATE"
            ), {"fid": feedback_id, "sid": shop_id}).fetchone()
            if not check:
                return "评价不存在"
            if check[1] == 2:
                return "该评价已回复"
            conn.execute(text(
                "UPDATE feedbacks SET reply_content = :reply, status = 2, replied_by = :oid, replied_at = NOW(), updated_at = NOW() WHERE id = :fid AND shop_id = :sid"
            ), {"reply": reply_content, "fid": feedback_id, "sid": shop_id, "oid": operator_id})
        return f"回复成功"
    except Exception as e:
        return f"回复失败: {str(e)}"
