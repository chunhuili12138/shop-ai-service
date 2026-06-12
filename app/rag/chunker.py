"""
智能分块器
支持按Markdown标题、语义、固定大小分块
"""

from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
)
from app.config import settings


# Markdown标题分割配置
MARKDOWN_HEADERS = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
]


def get_text_splitter() -> RecursiveCharacterTextSplitter:
    """获取文本分割器"""
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.RAG_CHUNK_SIZE,
        chunk_overlap=settings.RAG_CHUNK_OVERLAP,
        length_function=len,
        add_start_index=True,
    )


def get_markdown_splitter() -> MarkdownHeaderTextSplitter:
    """获取Markdown分割器"""
    return MarkdownHeaderTextSplitter(headers_to_split_on=MARKDOWN_HEADERS)


def split_document(text: str, file_type: str = "text") -> list[str]:
    """
    智能分块文档
    
    Args:
        text: 文档内容
        file_type: 文件类型 (text/markdown)
    
    Returns:
        分块后的文档列表
    """
    if file_type == "markdown":
        # 先按Markdown标题分块，再按大小细分
        md_splitter = get_markdown_splitter()
        md_chunks = md_splitter.split_text(text)

        text_splitter = get_text_splitter()
        all_chunks = []
        for chunk in md_chunks:
            sub_chunks = text_splitter.split_text(chunk.page_content)
            all_chunks.extend(sub_chunks)
        return all_chunks
    else:
        # 普通文本按固定大小分块
        text_splitter = get_text_splitter()
        return text_splitter.split_text(text)
