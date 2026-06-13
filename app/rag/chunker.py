"""
语义分块工具
根据语义边界进行文档分块，保持上下文完整性
"""

import re
from typing import List, Dict


def semantic_chunk(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    separators: List[str] = None
) -> List[Dict[str, str]]:
    """
    语义分块
    
    策略：
    1. 按标题（#）分割
    2. 按段落（\n\n）分割
    3. 按句子（。！？.!?）分割
    4. 保持块大小在 chunk_size 附近
    5. 添加 chunk_overlap 重叠
    
    Args:
        text: 原始文本
        chunk_size: 目标块大小（字符数）
        chunk_overlap: 重叠大小
        separators: 自定义分隔符
    
    Returns:
        分块列表 [{"content": str, "metadata": dict}]
    """
    if not text or not text.strip():
        return []
    
    # 默认分隔符（按优先级）
    if separators is None:
        separators = [
            "\n# ",      # 一级标题
            "\n## ",     # 二级标题
            "\n### ",    # 三级标题
            "\n\n",      # 段落
            "。",        # 中文句号
            "！",        # 中文感叹号
            "？",        # 中文问号
            ". ",        # 英文句号
            "! ",        # 英文感叹号
            "? ",        # 英文问号
            "\n",        # 换行
        ]
    
    # 递归分割
    chunks = _recursive_split(text, separators, chunk_size)
    
    # 添加重叠
    if chunk_overlap > 0 and len(chunks) > 1:
        chunks = _add_overlap(chunks, chunk_overlap)
    
    # 过滤太短的块
    chunks = [c for c in chunks if len(c.strip()) >= 10]
    
    return [{"content": c.strip(), "metadata": {"chunk_size": len(c.strip())}} for c in chunks]


def _recursive_split(
    text: str,
    separators: List[str],
    chunk_size: int
) -> List[str]:
    """递归分割文本"""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    
    # 尝试每个分隔符
    for sep in separators:
        if sep in text:
            splits = text.split(sep)
            
            # 合并小块
            chunks = []
            current_chunk = ""
            
            for i, split in enumerate(splits):
                # 添加分隔符（除了第一个）
                if i > 0:
                    split = sep + split
                
                if len(current_chunk) + len(split) <= chunk_size:
                    current_chunk += split
                else:
                    if current_chunk.strip():
                        chunks.append(current_chunk)
                    
                    # 如果单个块太大，递归分割
                    if len(split) > chunk_size:
                        sub_chunks = _recursive_split(split, separators[1:], chunk_size)
                        chunks.extend(sub_chunks)
                        current_chunk = ""
                    else:
                        current_chunk = split
            
            if current_chunk.strip():
                chunks.append(current_chunk)
            
            return chunks
    
    # 没有找到分隔符，按字符数硬分割
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i+chunk_size])
    
    return chunks


def _add_overlap(chunks: List[str], overlap_size: int) -> List[str]:
    """添加重叠"""
    if len(chunks) <= 1:
        return chunks
    
    result = [chunks[0]]
    
    for i in range(1, len(chunks)):
        # 从上一个块的末尾取 overlap_size 个字符
        prev_chunk = chunks[i-1]
        overlap = prev_chunk[-overlap_size:] if len(prev_chunk) > overlap_size else prev_chunk
        
        # 添加到当前块的开头
        result.append(overlap + chunks[i])
    
    return result


def simple_chunk(text: str, chunk_size: int = 500) -> List[Dict[str, str]]:
    """
    简单分块（按段落）
    
    Args:
        text: 原始文本
        chunk_size: 目标块大小
    
    Returns:
        分块列表
    """
    if not text or not text.strip():
        return []
    
    # 按段落分块
    paragraphs = text.split("\n\n")
    
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        if len(current_chunk) + len(para) + 2 <= chunk_size:
            if current_chunk:
                current_chunk += "\n\n"
            current_chunk += para
        else:
            if current_chunk.strip():
                chunks.append({"content": current_chunk.strip(), "metadata": {"chunk_size": len(current_chunk.strip())}})
            
            # 如果单个段落太大，按句子分块
            if len(para) > chunk_size:
                sentences = re.split(r'[。！？.!?]', para)
                for sent in sentences:
                    if sent.strip():
                        chunks.append({"content": sent.strip(), "metadata": {"chunk_size": len(sent.strip())}})
                current_chunk = ""
            else:
                current_chunk = para
    
    if current_chunk.strip():
        chunks.append({"content": current_chunk.strip(), "metadata": {"chunk_size": len(current_chunk.strip())}})
    
    return chunks


def split_document(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[Dict[str, str]]:
    """
    文档分块（对外接口）
    
    Args:
        text: 原始文本
        chunk_size: 目标块大小（字符数）
        chunk_overlap: 重叠大小
    
    Returns:
        分块列表 [{"content": str, "metadata": dict}]
    """
    return semantic_chunk(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
