"""
通知消息工具
查询通知列表、发送通知
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class NotificationsQueryInput(BaseModel):
    """通知查询参数"""
    shop_id: int = Field(description="店铺ID")
    recipient_type: Optional[str] = Field(
        default=None,
        description="接收者类型: staff=员工, customer=顾客（可选）"
    )
    limit: int = Field(default=10, description="返回数量，默认10")


class SendNotificationInput(BaseModel):
    """发送通知参数"""
    shop_id: int = Field(description="店铺ID")
    recipient_ids: str = Field(description="接收者ID列表，逗号分隔")
    title: str = Field(description="通知标题")
    content: str = Field(description="通知内容")


# ==================== Tools ====================

@tool(args_schema=NotificationsQueryInput)
def query_notifications(shop_id: int, recipient_type: Optional[str] = None, limit: int = 10) -> str:
    """
    查询通知列表。
    返回通知标题、内容、接收者类型、渠道、状态、时间。
    """
    sql = """
        SELECT
            id,
            title,
            content,
            recipient_type,
            recipient_id,
            channel,
            status,
            created_at
        FROM notification_logs
        WHERE shop_id = :shop_id
    """

    params = {"shop_id": shop_id, "limit": limit}

    if recipient_type:
        if recipient_type == "staff":
            sql += " AND recipient_type = 1"
        elif recipient_type == "customer":
            sql += " AND recipient_type = 2"

    sql += " ORDER BY created_at DESC LIMIT :limit"

    try:
        results = execute_sql(sql, params)

        if not results:
            return "暂无通知"

        type_names = {1: "员工", 2: "顾客"}
        channel_names = {1: "站内信", 2: "短信", 3: "微信"}
        status_names = {0: "未读", 1: "已读"}

        output = "通知列表:\n"
        for row in results:
            type_name = type_names.get(row["recipient_type"], "未知")
            channel_name = channel_names.get(row["channel"], "未知")
            status_name = status_names.get(row["status"], "未知")
            title = row["title"]
            content = row["content"][:50] + "..." if row.get("content") and len(row["content"]) > 50 else row.get("content", "")

            output += f"- [{row['id']}] {title} ({type_name}/{channel_name})\n"
            output += f"  内容: {content}\n"
            output += f"  状态: {status_name} | 时间: {row['created_at']}\n"

        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=SendNotificationInput)
def send_notification(shop_id: int, recipient_ids: str, title: str, content: str) -> str:
    """
    发送通知给员工或顾客。
    接收者ID用逗号分隔，发送站内信通知。
    """
    # 解析接收者ID
    id_list = [int(id.strip()) for id in recipient_ids.split(",") if id.strip()]

    if not id_list:
        return "请提供有效的接收者ID"

    try:
        success_count = 0
        fail_count = 0

        for recipient_id in id_list:
            try:
                insert_sql = """
                    INSERT INTO notification_logs
                    (shop_id, recipient_type, recipient_id, channel, title, content, status, created_at)
                    VALUES (:shop_id, 1, :recipient_id, 1, :title, :content, 0, NOW())
                """
                execute_sql(insert_sql, {
                    "shop_id": shop_id,
                    "recipient_id": recipient_id,
                    "title": title,
                    "content": content
                })
                success_count += 1
            except Exception:
                fail_count += 1

        return f"发送完成: 成功 {success_count} 条，失败 {fail_count} 条"

    except Exception as e:
        return f"发送失败: {str(e)}"
