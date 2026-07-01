"""
文件上传模块
支持图片识别和文档文件读取
"""

from app.file.router import router as file_router
from app.file.parser import parse_document, ParseError

__all__ = [
    "file_router",
    "parse_document",
    "ParseError",
]
