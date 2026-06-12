"""
搜索模块
提供互联网搜索功能（Tavily）
"""

from app.search.tavily_client import TavilySearchClient, get_search_client, web_search

__all__ = [
    "TavilySearchClient",
    "get_search_client",
    "web_search",
]
