"""
数据格式化模块
将查询结果格式化为前端可渲染的结构化数据
"""

from app.formatter.data_formatter import DataFormatter, get_data_formatter

__all__ = [
    "DataFormatter",
    "get_data_formatter",
]
