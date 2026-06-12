"""
BM25检索器
基于关键词的稀疏检索，擅长精确匹配专有名词
"""

import jieba
from rank_bm25 import BM25Okapi
from pathlib import Path
from typing import Optional


class BM25Retriever:
    """
    BM25检索器
    
    特点：
    - 基于关键词匹配
    - 擅长专有名词（如"周卡"、"月卡"、"退款"）
    - 不需要向量化，速度快
    """

    def __init__(self):
        self.corpus = []  # 原始文档列表
        self.tokenized_corpus = []  # 分词后的文档列表
        self.bm25 = None
        self.doc_metadatas = []  # 文档元数据

    def build_index(self, documents: list[str], metadatas: list[dict] = None):
        """
        构建BM25索引
        
        Args:
            documents: 文档列表
            metadatas: 文档元数据列表
        """
        self.corpus = documents
        self.doc_metadatas = metadatas or [{} for _ in documents]
        
        # 使用jieba进行中文分词
        self.tokenized_corpus = [
            list(jieba.cut(doc)) for doc in documents
        ]
        
        # 构建BM25索引
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        
        print(f"[BM25] 索引构建完成，共{len(documents)}个文档")

    def search(self, query: str, k: int = 5) -> list[dict]:
        """
        BM25检索
        
        Args:
            query: 查询文本
            k: 返回结果数量
        
        Returns:
            检索结果列表 [{"content": str, "score": float, "metadata": dict}]
        """
        if self.bm25 is None:
            return []

        # 对查询进行分词
        tokenized_query = list(jieba.cut(query))
        
        # 计算BM25分数
        scores = self.bm25.get_scores(tokenized_query)
        
        # 获取Top-K结果
        top_k_indices = scores.argsort()[-k:][::-1]
        
        results = []
        for idx in top_k_indices:
            if scores[idx] > 0:  # 只返回有分数的结果
                results.append({
                    "content": self.corpus[idx],
                    "score": float(scores[idx]),
                    "metadata": self.doc_metadatas[idx],
                })
        
        return results

    def add_documents(self, documents: list[str], metadatas: list[dict] = None):
        """
        添加文档并重建索引
        """
        new_metadatas = metadatas or [{} for _ in documents]
        self.corpus.extend(documents)
        self.doc_metadatas.extend(new_metadatas)
        
        # 重建索引
        self.build_index(self.corpus, self.doc_metadatas)


def load_documents_from_dir(dir_path: str) -> tuple[list[str], list[dict]]:
    """
    从目录加载文档
    
    Returns:
        (documents, metadatas) 元组
    """
    from app.rag.parser import parse_file
    from app.rag.chunker import split_document
    
    documents = []
    metadatas = []
    
    path = Path(dir_path)
    if not path.exists():
        return documents, metadatas
    
    for file_path in path.rglob("*.md"):
        try:
            content, file_type = parse_file(str(file_path))
            chunks = split_document(content, file_type)
            
            for chunk in chunks:
                documents.append(chunk)
                metadatas.append({
                    "source": str(file_path),
                    "type": file_type,
                })
        except Exception as e:
            print(f"[BM25] 解析文件失败: {file_path}, 错误: {e}")
    
    return documents, metadatas


# 全局BM25检索器实例
_bm25_retriever = None


def get_bm25_retriever() -> BM25Retriever:
    """获取BM25检索器单例"""
    global _bm25_retriever
    if _bm25_retriever is None:
        _bm25_retriever = BM25Retriever()
        
        # 从data目录加载文档
        documents, metadatas = load_documents_from_dir("data/knowledge")
        if documents:
            _bm25_retriever.build_index(documents, metadatas)
    
    return _bm25_retriever
