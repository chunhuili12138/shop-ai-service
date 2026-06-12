"""
嵌入模型封装
默认通过 Ollama 本地运行 bge-m3，也兼容 OpenAI 兼容的云 Embedding API
"""

from langchain_openai import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings
from app.config import settings


def get_embeddings() -> Embeddings:
    """获取嵌入模型实例"""
    if not settings.EMBEDDING_BASE_URL:
        raise ValueError("请配置 EMBEDDING_BASE_URL（如 http://localhost:11434/v1）")

    kwargs = {
        "model": settings.EMBEDDING_MODEL,
        "openai_api_key": settings.EMBEDDING_API_KEY or "ollama",
        "openai_api_base": settings.EMBEDDING_BASE_URL,
        "check_embedding_ctx_length": settings.EMBEDDING_CHECK_CTX_LENGTH,
    }
    if settings.EMBEDDING_USE_CUSTOM_DIMENSIONS:
        kwargs["dimensions"] = settings.EMBEDDING_DIMENSIONS

    return OpenAIEmbeddings(**kwargs)
