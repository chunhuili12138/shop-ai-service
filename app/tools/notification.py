"""
通知消息工具
查询通知列表、发送通知（HITL）
"""

import json
from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql, get_engine


class NotificationsQueryInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    recipient_type: Optional[str] = Field(default=None, description="类型: staff=员工, customer=顾客")
    limit: int = Field(default=10, description="返回数量")

class SendNotificationInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    recipient_ids: str = Field(description="接收者ID列表，逗号分隔")
    recipient_type: str = Field(default="staff", description="接收者类型: staff=员工, customer=顾客")
    title: str = Field(description="通知标题")
    content: str = Field(description="通知内容")


@tool(args_schema=NotificationsQueryInput)
def query_notifications(shop_id: int, recipient_type: Optional[str] = None, limit: int = 10) -> str:
    """查询通知列表。"""
    sql = """
        SELECT id, title, content, recipient_type, recipient_id, channel, status, created_at
        FROM notification_logs WHERE shop_id = :shop_id
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
            tn = type_names.get(row["recipient_type"], "未知")
            cn = channel_names.get(row["channel"], "未知")
            sn = status_names.get(row["status"], "未知")
            content = (row["content"] or "")[:50]
            output += f"- [{row['id']}] {row['title']} ({tn}/{cn})\n"
            output += f"  内容: {content}\n"
            output += f"  状态: {sn} | 时间: {row['created_at']}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=SendNotificationInput)
def send_notification(shop_id: int, recipient_ids: str, recipient_type: str = "staff", title: str = "", content: str = "") -> dict:
    """发送通知。返回确认框，需用户确认后执行。"""
    id_list = [int(i.strip()) for i in recipient_ids.split(",") if i.strip()]
    if not id_list:
        return {"type": "error", "message": "请提供有效的接收者ID"}
    rt = 1 if recipient_type == "staff" else 2
    rt_name = "员工" if rt == 1 else "顾客"
    return {
        "type": "confirm",
        "tool_name": "send_notification",
        "title": "确认发送通知",
        "message": f"确定要向 {len(id_list)} 位{rt_name}发送通知吗？",
        "details": {
            "接收者类型": rt_name,
            "接收人数": str(len(id_list)),
        },
        "fields": [
            {"name": "title", "type": "input", "label": "通知标题", "required": True, "placeholder": "请输入通知标题", "value": title or ""},
            {"name": "content", "type": "textarea", "label": "通知内容", "required": True, "placeholder": "请输入通知内容", "value": content or ""}
        ],
        "buttons": [
            {"type": "confirm", "label": "确认发送"},
            {"type": "cancel", "label": "取消"}
        ],
        "action": "send_notification",
        "params": {
            "shop_id": shop_id, "recipient_ids": recipient_ids,
            "recipient_type": recipient_type, "title": title, "content": content
        }
    }


def execute_send_notification(shop_id: int, recipient_ids: str, recipient_type: str = "staff", title: str = "", content: str = "", operator_id: Optional[int] = None) -> str:
    """执行发送通知（事务）"""
    engine = get_engine()
    try:
        id_list = [int(i.strip()) for i in recipient_ids.split(",") if i.strip()]
        if not id_list:
            return "请提供有效的接收者ID"
        rt = 1 if recipient_type == "staff" else 2
        with engine.begin() as conn:
            from sqlalchemy import text
            success = 0
            for rid in id_list:
                try:
                    conn.execute(text(
                        "INSERT INTO notification_logs (shop_id, recipient_type, recipient_id, channel, title, content, status, created_at) "
                        "VALUES (:sid, :rt, :rid, 1, :title, :content, 0, NOW())"
                    ), {"sid": shop_id, "rt": rt, "rid": rid, "title": title, "content": content})
                    success += 1
                except Exception:
                    pass
        return f"发送完成: 成功 {success} 条"
    except Exception as e:
        return f"发送失败: {str(e)}"
