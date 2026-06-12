"""
知识库同步路由
提供手动触发同步的API接口
"""

import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
from app.knowledge.sync import knowledge_sync
from app.rag.parser import parse_directory
from app.rag.chunker import split_document
from app.rag.vectorstore import add_documents

router = APIRouter()

# 意图分组目录
INTENT_DIRS = [
    "data/knowledge/package",
    "data/knowledge/hours",
    "data/knowledge/refund",
    "data/knowledge/rules",
    "data/knowledge/general",
]


class SyncResponse(BaseModel):
    """同步响应"""
    success: bool
    message: str
    results: dict


@router.post("/sync", response_model=SyncResponse)
async def trigger_sync(shop_id: int = 5):
    """
    手动触发知识库同步
    
    流程：
    1. 从MySQL数据库/API导出数据
    2. 生成Markdown文档（按意图分组）
    3. 索引到向量库
    """
    try:
        # 步骤1：从数据库/API同步数据到文档（使用 asyncio.to_thread 包装同步调用）
        sync_results = await asyncio.to_thread(knowledge_sync.sync_all, shop_id)
        
        # 步骤2：索引文档到向量库（按意图分组目录）
        index_results = await asyncio.to_thread(index_all_knowledge)
        
        return SyncResponse(
            success=True,
            message="知识库同步完成",
            results={
                "sync": sync_results,
                "index": index_results,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


@router.get("/status")
async def get_sync_status():
    """获取同步状态"""
    all_files = []
    
    for intent_dir in INTENT_DIRS:
        dir_path = Path(intent_dir)
        if dir_path.exists():
            for f in dir_path.glob("*.md"):
                all_files.append({
                    "name": f.name,
                    "path": str(f),
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                    "intent": intent_dir.split("/")[-1],
                })
    
    return {
        "intent_dirs": INTENT_DIRS,
        "file_count": len(all_files),
        "files": all_files,
    }


def index_all_knowledge() -> dict:
    """索引所有意图分组的文档"""
    total_files = 0
    total_chunks = 0
    
    for intent_dir in INTENT_DIRS:
        result = index_documents(intent_dir)
        total_files += result.get("file_count", 0)
        total_chunks += result.get("chunk_count", 0)
    
    return {
        "intent_dirs": len(INTENT_DIRS),
        "file_count": total_files,
        "chunk_count": total_chunks,
    }


def index_documents(directory: str) -> dict:
    """索引文档到向量库"""
    files = parse_directory(directory)
    if not files:
        return {"message": "未找到可索引的文档", "count": 0}

    all_texts = []
    all_metadatas = []
    for file_info in files:
        chunks = split_document(file_info["content"], file_info["type"])
        for chunk in chunks:
            all_texts.append(chunk)
            all_metadatas.append({
                "source": file_info["path"],
                "type": file_info["type"],
            })

    ids = add_documents(all_texts, all_metadatas)
    return {
        "file_count": len(files),
        "chunk_count": len(ids),
    }
