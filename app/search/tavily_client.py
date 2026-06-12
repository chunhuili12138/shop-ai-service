"""
Tavily 搜索客户端
提供互联网搜索功能，用于获取实时信息
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from app.config import settings


@dataclass
class SearchResult:
    """搜索结果"""
    title: str
    url: str
    content: str
    score: float = 0.0


@dataclass
class SearchResponse:
    """搜索响应"""
    query: str
    answer: str  # AI 生成的答案摘要
    results: List[SearchResult]
    raw_response: Dict[str, Any] = None


class TavilySearchClient:
    """
    Tavily 搜索客户端
    
    功能：
    - 执行互联网搜索
    - 获取实时信息
    - AI 生成答案摘要
    """
    
    def __init__(self, api_key: str = None):
        """
        初始化搜索客户端
        
        Args:
            api_key: Tavily API Key（可选，默认从配置读取）
        """
        self.api_key = api_key or settings.TAVILY_API_KEY
        self._client = None
    
    @property
    def client(self):
        """懒加载 Tavily 客户端"""
        if self._client is None:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=self.api_key)
            except Exception as e:
                print(f"[Tavily] 初始化失败: {str(e)}")
                raise
        return self._client
    
    def search(
        self, 
        query: str, 
        search_depth: str = "basic",
        max_results: int = 5,
        include_answer: bool = True,
        **kwargs
    ) -> SearchResponse:
        """
        执行搜索
        
        Args:
            query: 搜索查询
            search_depth: 搜索深度（basic/advanced）
            max_results: 最大结果数
            include_answer: 是否包含 AI 生成的答案摘要
            **kwargs: 其他参数
        
        Returns:
            SearchResponse 搜索响应
        """
        try:
            # 执行搜索
            response = self.client.search(
                query=query,
                search_depth=search_depth,
                max_results=max_results,
                include_answer=include_answer,
                **kwargs
            )
            
            # 解析结果
            results = []
            for item in response.get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    score=item.get("score", 0.0),
                ))
            
            return SearchResponse(
                query=query,
                answer=response.get("answer", ""),
                results=results,
                raw_response=response,
            )
        except Exception as e:
            print(f"[Tavily] 搜索失败: {str(e)}")
            return SearchResponse(
                query=query,
                answer=f"搜索失败: {str(e)}",
                results=[],
            )
    
    def search_with_context(
        self, 
        query: str, 
        context: str = "",
        max_results: int = 3,
        language: str = "zh",
    ) -> str:
        """
        执行搜索并返回格式化的上下文
        
        Args:
            query: 搜索查询
            context: 额外上下文（如店铺信息）
            max_results: 最大结果数
            language: 语言（zh=中文, en=英文）
        
        Returns:
            格式化的搜索结果文本
        """
        try:
            # 构建搜索查询（添加语言提示）
            search_query = query
            if context:
                search_query = f"{context} {query}"
            
            # 如果是中文查询，添加中文搜索提示
            if language == "zh" and not any('\u4e00' <= c <= '\u9fff' for c in search_query):
                # 查询中没有中文字符，添加中文搜索词
                search_query = f"{search_query} 中文"
            
            # 执行搜索
            response = self.search(
                query=search_query,
                max_results=max_results,
                include_answer=True,
            )
            
            # 格式化结果
            formatted = []
            
            # 添加 AI 答案摘要
            if response.answer:
                formatted.append(f"**搜索摘要**：{response.answer}")
            
            # 添加详细结果
            if response.results:
                formatted.append("\n**详细信息**：")
                for i, result in enumerate(response.results[:max_results], 1):
                    formatted.append(f"{i}. **{result.title}**")
                    formatted.append(f"   {result.content[:200]}...")
                    formatted.append(f"   来源: {result.url}")
            
            return "\n".join(formatted) if formatted else "未找到相关信息"
        except Exception as e:
            print(f"[Tavily] 搜索失败: {str(e)}")
            return f"搜索失败: {str(e)}"


# 全局实例
_search_client = None


def get_search_client() -> TavilySearchClient:
    """获取搜索客户端实例"""
    global _search_client
    if _search_client is None:
        _search_client = TavilySearchClient()
    return _search_client


async def web_search(query: str, context: str = "", max_results: int = 3, language: str = "zh") -> str:
    """
    互联网搜索（异步包装）
    
    Args:
        query: 搜索查询
        context: 额外上下文
        max_results: 最大结果数
        language: 语言（zh=中文, en=英文）
    
    Returns:
        格式化的搜索结果
    """
    import asyncio
    
    try:
        client = get_search_client()
        # 在线程池中执行同步搜索
        result = await asyncio.to_thread(
            client.search_with_context,
            query=query,
            context=context,
            max_results=max_results,
            language=language,
        )
        return result
    except Exception as e:
        print(f"[WebSearch] 搜索失败: {str(e)}")
        return f"搜索失败: {str(e)}"
