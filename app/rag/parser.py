"""
文档解析器
支持解析 PDF、Word、Markdown、纯文本
"""

import os
from pathlib import Path


def parse_file(file_path: str) -> tuple[str, str]:
    """
    解析文件，返回 (内容, 文件类型)
    
    Args:
        file_path: 文件路径
    
    Returns:
        (content, file_type) 元组
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".md":
        return parse_markdown(file_path)
    elif suffix == ".txt":
        return parse_text(file_path)
    elif suffix == ".pdf":
        return parse_pdf(file_path)
    else:
        raise ValueError(f"不支持的文件类型: {suffix}")


def parse_markdown(file_path: str) -> tuple[str, str]:
    """解析Markdown文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return content, "markdown"


def parse_text(file_path: str) -> tuple[str, str]:
    """解析纯文本文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    return content, "text"


def parse_pdf(file_path: str) -> tuple[str, str]:
    """
    解析PDF文件
    需要安装: pip install pymupdf
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        content = ""
        for page in doc:
            content += page.get_text()
        doc.close()
        return content, "text"
    except ImportError:
        raise ImportError("请安装 PyMuPDF: pip install pymupdf")


def parse_directory(dir_path: str, extensions: list[str] = None) -> list[dict]:
    """
    批量解析目录下的文件
    
    Args:
        dir_path: 目录路径
        extensions: 允许的文件扩展名，默认 [".md", ".txt", ".pdf"]
    
    Returns:
        文件内容列表 [{"path": str, "content": str, "type": str}]
    """
    if extensions is None:
        extensions = [".md", ".txt", ".pdf"]

    results = []
    path = Path(dir_path)

    if not path.exists():
        return results

    for file_path in path.rglob("*"):
        if file_path.suffix.lower() in extensions:
            try:
                content, file_type = parse_file(str(file_path))
                results.append({
                    "path": str(file_path),
                    "content": content,
                    "type": file_type,
                })
            except Exception as e:
                print(f"解析文件失败: {file_path}, 错误: {e}")

    return results
