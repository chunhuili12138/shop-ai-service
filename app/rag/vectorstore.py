"""
向量库操作封装
支持 Chroma（开发）和 Milvus（生产）
"""

import logging
from langchain_chroma import Chroma
from langchain_core.vectorstores import VectorStore
from app.config import settings
from app.rag.embeddings import get_embeddings
from app.chroma_config import chroma_settings

logger = logging.getLogger(__name__)


def get_vectorstore() -> VectorStore:
    """获取向量库实例（带 HNSW 参数优化）"""
    embeddings = get_embeddings()

    if settings.VECTOR_STORE_TYPE == "chroma":
        vs = Chroma(
            collection_name=settings.CHROMA_COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=settings.CHROMA_PERSIST_DIR,
            client_settings=chroma_settings,
        )
        # 设置 HNSW 参数（解决 "ef or M is too small" 错误）
        try:
            collection = vs._collection
            collection.modify(metadata={
                "hnsw:space": "cosine",
                "hnsw:M": 32,
                "hnsw:construction_ef": 200,
                "hnsw:search_ef": 100,
            })
        except Exception:
            pass  # 首次创建时可能失败，不影响使用
        return vs
    else:
        raise ValueError(f"不支持的向量库类型: {settings.VECTOR_STORE_TYPE}")


def rebuild_index():
    """
    从 data/knowledge/ 重建 ChromaDB 索引

    流程：
    1. 加载所有 .md 文件
    2. 分块
    3. 清空旧 collection
    4. add_texts 到 ChromaDB
    """
    try:
        from app.rag.bm25_retriever import load_documents_from_dir
        from pathlib import Path

        knowledge_dir = str(Path(__file__).parent.parent.parent / "data" / "knowledge")
        logger.info(f"[VectorStore] 开始重建索引: {knowledge_dir}")

        # 1. 加载文档
        documents, metadatas = load_documents_from_dir(knowledge_dir)
        if not documents:
            logger.warning("[VectorStore] 没有找到文档，跳过索引重建")
            return False

        logger.info(f"[VectorStore] 加载了 {len(documents)} 个文档块")

        # 2. 获取向量库
        vectorstore = get_vectorstore()

        # 3. 清空旧 collection
        try:
            existing = vectorstore._collection.get()
            if existing and existing.get("ids"):
                vectorstore._collection.delete(ids=existing["ids"])
                logger.info(f"[VectorStore] 清空旧索引: {len(existing['ids'])} 条")
        except Exception as e:
            logger.warning(f"[VectorStore] 清空旧索引失败: {str(e)}")

        # 4. 批量添加
        texts = [doc if isinstance(doc, str) else str(doc) for doc in documents]
        vectorstore.add_texts(texts=texts, metadatas=metadatas)
        logger.info(f"[VectorStore] 索引重建完成: {len(texts)} 个文档块")

        return True

    except Exception as e:
        logger.error(f"[VectorStore] 索引重建失败: {str(e)}")
        return False


def add_documents(texts: list[str], metadatas: list[dict] = None) -> list[str]:
    """添加文档到向量库"""
    vectorstore = get_vectorstore()
    ids = vectorstore.add_texts(texts=texts, metadatas=metadatas)
    return ids


def similarity_search(query: str, k: int = None) -> list:
    """相似性搜索"""
    if k is None:
        k = settings.RAG_TOP_K
    vectorstore = get_vectorstore()
    return vectorstore.similarity_search_with_score(query, k=k)
