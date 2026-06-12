"""
向量库操作封装
支持 Chroma（开发）和 Milvus（生产）
"""

from langchain_chroma import Chroma
from langchain_core.vectorstores import VectorStore
from app.config import settings
from app.rag.embeddings import get_embeddings
from app.chroma_config import chroma_settings


def get_vectorstore() -> VectorStore:
    """获取向量库实例"""
    embeddings = get_embeddings()

    if settings.VECTOR_STORE_TYPE == "chroma":
        return Chroma(
            collection_name=settings.CHROMA_COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=settings.CHROMA_PERSIST_DIR,
            client_settings=chroma_settings,
        )
    else:
        raise ValueError(f"不支持的向量库类型: {settings.VECTOR_STORE_TYPE}")


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
