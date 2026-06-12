"""
Reranker重排序器
对检索结果进行二次排序，提高最终结果的相关性
"""

from typing import Optional
from app.config import settings


class SimpleReranker:
    """
    简单Reranker
    
    基于规则的重排序：
    1. 关键词匹配加分
    2. 文档长度惩罚
    3. 来源类型加分
    """

    def rerank(
        self, 
        query: str, 
        results: list[dict], 
        top_k: int = 3
    ) -> list[dict]:
        """
        对检索结果进行重排序
        
        Args:
            query: 查询文本
            results: 检索结果列表
            top_k: 返回结果数量
        
        Returns:
            重排序后的结果列表
        """
        if not results:
            return []

        # 计算每个结果的重排序分数
        scored_results = []
        for result in results:
            score = self._calculate_score(query, result)
            scored_results.append({**result, "rerank_score": score})
        
        # 按重排序分数排序
        scored_results.sort(key=lambda x: x["rerank_score"], reverse=True)
        
        # 返回Top-K结果
        return scored_results[:top_k]

    def _calculate_score(self, query: str, result: dict) -> float:
        """
        计算重排序分数
        
        策略：
        1. 原始分数（向量相似度或BM25分数）
        2. 关键词匹配加分
        3. 文档长度惩罚
        """
        base_score = result.get("score", 0) or result.get("relevance_score", 0)
        
        # 关键词匹配加分
        keyword_bonus = self._keyword_match_score(query, result.get("content", ""))
        
        # 文档长度惩罚（太长或太短都扣分）
        length_penalty = self._length_penalty(result.get("content", ""))
        
        # 最终分数
        final_score = base_score + keyword_bonus + length_penalty
        
        return final_score

    def _keyword_match_score(self, query: str, content: str) -> float:
        """
        关键词匹配加分
        
        如果查询关键词在文档中出现，给予加分
        """
        bonus = 0.0
        
        # 简单的关键词匹配
        query_lower = query.lower()
        content_lower = content.lower()
        
        # 检查查询词是否在文档中
        if query_lower in content_lower:
            bonus += 0.3
        
        # 检查单个字/词是否匹配
        for char in query:
            if char in content_lower and len(char.strip()) > 0:
                bonus += 0.05
        
        return min(bonus, 0.5)  # 最大加分0.5

    def _length_penalty(self, content: str) -> float:
        """
        文档长度惩罚
        
        太短或太长的文档都扣分
        """
        length = len(content)
        
        if length < 10:
            return -0.2  # 太短，扣分
        elif length > 1000:
            return -0.1  # 太长，轻微扣分
        else:
            return 0.0  # 合适长度


class LLMReranker:
    """
    LLM Reranker（可选，需要调用LLM）
    
    使用LLM判断文档与查询的相关性
    """

    def __init__(self):
        self.llm = None

    def _get_llm(self):
        """延迟加载LLM"""
        if self.llm is None:
            from app.llm import get_chat_llm
            self.llm = get_chat_llm(temperature=0)
        return self.llm

    def rerank(
        self, 
        query: str, 
        results: list[dict], 
        top_k: int = 3
    ) -> list[dict]:
        """
        使用LLM进行重排序
        
        注意：这个方法会调用LLM，速度较慢，适合高精度场景
        """
        if not results or len(results) <= top_k:
            return results

        try:
            llm = self._get_llm()
            
            # 构建评分Prompt
            prompt = f"""请判断以下文档与查询的相关性，返回0-10的分数。

查询：{query}

"""
            for i, result in enumerate(results[:10]):  # 最多处理10个
                content = result.get("content", "")[:200]  # 截断过长内容
                prompt += f"文档{i+1}: {content}\n\n"

            prompt += """请返回JSON格式的评分结果，例如：
{"scores": [8, 6, 9, ...]}

只返回JSON，不要其他解释。"""

            # 调用LLM
            response = llm.invoke([{"role": "user", "content": prompt}])
            
            # 解析评分（简化处理）
            import json
            import re
            
            # 尝试提取JSON
            json_match = re.search(r'\{[^}]+\}', response.content)
            if json_match:
                scores_data = json.loads(json_match.group())
                scores = scores_data.get("scores", [])
                
                # 更新分数
                for i, score in enumerate(scores[:len(results)]):
                    results[i]["rerank_score"] = score / 10.0  # 归一化到0-1
                
                # 重新排序
                results.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
            
            return results[:top_k]
            
        except Exception as e:
            print(f"[LLM Reranker] 失败: {str(e)}")
            # 降级到简单重排序
            return SimpleReranker().rerank(query, results, top_k)


# 全局Reranker实例
_reranker = None


def get_reranker() -> SimpleReranker:
    """获取Reranker实例"""
    global _reranker
    if _reranker is None:
        _reranker = SimpleReranker()
    return _reranker
