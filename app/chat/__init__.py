"""
统一聊天模块
提供统一的聊天接口，自动路由到合适的模块
"""

from app.chat.router import router as chat_router
from app.chat.stream_handler import StreamHandler

__all__ = [
    "chat_router",
    "StreamHandler",
]
