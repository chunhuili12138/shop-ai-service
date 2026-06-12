"""
RAG检索器
支持混合检索（BM25 + 向量）+ Reranker重排序
"""

from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from pydantic import Field
from app.config import settings
from app.rag.vectorstore import get_vectorstore
from app.rag.bm25_retriever import get_bm25_retriever
from app.rag.reranker import get_reranker


class HybridRetriever(BaseRetriever):
    """
    混合检索器
    
    结合 BM25（关键词匹配）和 向量（语义匹配）检索，
    然后使用 Reranker 进行重排序。
    
    优势：
    - BM25：擅长精确匹配专有名词（如"周卡"、"退款"）
    - 向量：擅长语义理解（如"七天卡"≈"周卡"）
    - Reranker：二次排序提高准确性
    """

    bm25_weight: float = Field(default=0.3, description="BM25权重")
    vector_weight: float = Field(default=0.7, description="向量权重")
    use_reranker: bool = Field(default=True, description="是否使用Reranker")

    def _get_relevant_documents(self, query: str) -> list[Document]:
        """
        执行混合检索
        
        流程：
        1. 并行执行BM25检索和向量检索
        2. 合并并加权分数
        3. 使用Reranker重排序
        4. 返回Top-K结果
        """
        # 1. 向量检索
        vector_results = self._vector_search(query)
        
        # 2. BM25检索
        bm25_results = self._bm25_search(query)
        
        # 3. 合并结果
        merged_results = self._merge_results(vector_results, bm25_results)
        
        # 4. Reranker重排序
        if self.use_reranker and merged_results:
            reranker = get_reranker()
            merged_results = reranker.rerank(query, merged_results, top_k=settings.RAG_TOP_K)
        
        # 5. 转换为Document格式
        documents = []
        for result in merged_results:
            doc = Document(
                page_content=result["content"],
                metadata=result.get("metadata", {}),
            )
            doc.metadata["final_score"] = result.get("rerank_score", result.get("score", 0))
            documents.append(doc)
        
        return documents

    def _vector_search(self, query: str) -> list[dict]:
        """向量检索"""
        try:
            vectorstore = get_vectorstore()
            results = vectorstore.similarity_search_with_score(
                query, k=settings.RAG_TOP_K
            )
            
            # 归一化分数（向量检索返回的是距离，越小越相似）
            # 将距离转换为相似度分数
            normalized_results = []
            for doc, distance in results:
                # 使用sigmoid归一化
                similarity = 1 / (1 + distance)
                normalized_results.append({
                    "content": doc.page_content,
                    "score": similarity,
                    "metadata": doc.metadata,
                    "source": "vector",
                })
            
            return normalized_results
        except Exception as e:
            print(f"[混合检索] 向量检索失败: {str(e)}")
            return []

    def _bm25_search(self, query: str) -> list[dict]:
        """BM25检索"""
        try:
            bm25_retriever = get_bm25_retriever()
            results = bm25_retriever.search(query, k=settings.RAG_TOP_K)
            
            # BM25分数归一化
            if results:
                max_score = max(r["score"] for r in results)
                if max_score > 0:
                    for r in results:
                        r["score"] = r["score"] / max_score  # 归一化到0-1
                        r["source"] = "bm25"
            
            return results
        except Exception as e:
            print(f"[混合检索] BM25检索失败: {str(e)}")
            return []

    def _merge_results(
        self, 
        vector_results: list[dict], 
        bm25_results: list[dict]
    ) -> list[dict]:
        """
        合并检索结果
        
        策略：
        1. 将两个结果集按内容去重
        2. 加权计算最终分数
        """
        # 使用content作为去重key
        merged = {}
        
        # 处理向量结果
        for result in vector_results:
            content = result["content"]
            if content not in merged:
                merged[content] = {
                    "content": content,
                    "score": 0,
                    "metadata": result.get("metadata", {}),
                    "sources": [],
                }
            merged[content]["score"] += result["score"] * self.vector_weight
            merged[content]["sources"].append("vector")
        
        # 处理BM25结果
        for result in bm25_results:
            content = result["content"]
            if content not in merged:
                merged[content] = {
                    "content": content,
                    "score": 0,
                    "metadata": result.get("metadata", {}),
                    "sources": [],
                }
            merged[content]["score"] += result["score"] * self.bm25_weight
            merged[content]["sources"].append("bm25")
        
        # 按分数排序
        results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        
        return results


def get_retriever() -> BaseRetriever:
    """获取检索器实例"""
    return HybridRetriever()
