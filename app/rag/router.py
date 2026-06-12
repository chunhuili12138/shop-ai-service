"""
RAG模块路由
提供知识库问答API（支持Agentic RAG、追问、多轮对话）
所有接口需要 Token 验证
"""

import time
import asyncio
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from app.rag.chain import query_with_sources
from app.rag.agentic_rag import get_agentic_rag
from app.rag.session import get_session_manager
from app.rag.parser import parse_directory
from app.rag.chunker import split_document
from app.rag.vectorstore import add_documents
from app.config import settings
from app.common.auth import verify_token, parse_authorization
from monitoring.langfuse_config import create_trace, create_span

router = APIRouter()


class QueryRequest(BaseModel):
    """查询请求"""
    question: str


class QueryResponse(BaseModel):
    """查询响应"""
    answer: str
    sources: list
    confidence: float


class AgenticQueryRequest(BaseModel):
    """Agentic RAG查询请求"""
    question: str
    session_id: Optional[str] = None


class AgenticQueryResponse(BaseModel):
    """Agentic RAG响应（回答）"""
    type: str = "answer"
    answer: str
    intent: str
    intent_description: str
    sources: list
    confidence: float


class ClarificationResponse(BaseModel):
    """追问响应"""
    type: str = "clarification"
    clarification: dict


class IndexRequest(BaseModel):
    """索引请求"""
    directory: str
    file_types: list[str] = None


@router.post("/query", response_model=QueryResponse)
async def query_knowledge(
    request: QueryRequest,
    authorization: str = Header(...)
):
    """
    查询知识库（基础RAG）

    顾客可以询问：
    - 套餐信息和价格
    - 营业时间
    - 店铺位置和联系方式
    - 常见问题解答
    """
    # 创建追踪
    trace = create_trace("rag_query", {"question": request.question})
    start_time = time.time()
    
    try:
        # 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        result = await query_with_sources(request.question)
        
        # 记录追踪
        if trace:
            create_span(trace, "rag_result", {
                "answer_length": len(result.get("answer", "")),
                "confidence": result.get("confidence", 0),
                "source_count": len(result.get("sources", [])),
                "duration_ms": (time.time() - start_time) * 1000,
            })
        
        return QueryResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        if trace:
            create_span(trace, "rag_error", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.post("/query/agentic")
async def query_agentic_rag(
    request: AgenticQueryRequest,
    authorization: str = Header(...)
):
    """
    智能问答（Agentic RAG）

    支持功能：
    - 自动意图识别和路由
    - 低置信度时主动追问
    - 多轮对话上下文

    请求示例：
    {
        "question": "多少钱？",
        "session_id": "user_123"  # 可选
    }

    可能的响应：
    1. 直接回答（type=answer）
    2. 追问提示（type=clarification）
    """
    # 创建追踪
    trace = create_trace("agentic_rag_query", {
        "question": request.question,
        "session_id": request.session_id,
    })
    start_time = time.time()
    
    try:
        # 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        agentic_rag = get_agentic_rag()
        # 使用 asyncio.to_thread 包装同步调用，避免阻塞事件循环
        result = await asyncio.to_thread(
            agentic_rag.query,
            question=request.question,
            session_id=request.session_id,
            shop_id=user_context.shop_id,
        )

        # 记录追踪
        if trace:
            create_span(trace, "agentic_rag_result", {
                "type": result.get("type"),
                "intent": result.get("intent"),
                "confidence": result.get("confidence"),
                "answer_length": len(result.get("answer", "")),
                "duration_ms": (time.time() - start_time) * 1000,
            })

        if result.get("type") == "clarification":
            return ClarificationResponse(clarification=result["clarification"])
        else:
            return AgenticQueryResponse(
                answer=result["answer"],
                intent=result["intent"],
                intent_description=result["intent_description"],
                sources=result["sources"],
                confidence=result["confidence"],
            )
    except HTTPException:
        raise
    except Exception as e:
        if trace:
            create_span(trace, "agentic_rag_error", {"error": str(e)})
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.delete("/session/{session_id}")
async def clear_session(
    session_id: str,
    authorization: str = Header(...)
):
    """
    清空会话历史

    用于：
    - 用户主动结束对话
    - 会话超时清理
    """
    try:
        # 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        session_mgr = get_session_manager()
        session_mgr.clear_session(session_id)
        return {"message": "会话已清空", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空会话失败: {str(e)}")


@router.get("/session/{session_id}/history")
async def get_session_history(
    session_id: str,
    authorization: str = Header(...)
):
    """
    获取会话历史

    返回指定会话的对话历史
    """
    try:
        # 验证 Token
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        session_mgr = get_session_manager()
        history = session_mgr.get_history(session_id)
        return {
            "session_id": session_id,
            "history": history,
            "count": len(history),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取历史失败: {str(e)}")


@router.post("/index")
async def index_documents(
    request: IndexRequest,
    authorization: str = Header(...)
):
    """
    索引文档到知识库

    支持的目录：
    - data/knowledge/package: 套餐信息
    - data/knowledge/hours: 营业时间
    - data/knowledge/refund: 退款政策
    - data/knowledge/rules: 店铺规则
    - data/knowledge/general: 通用问题
    """
    try:
        # 验证 Token（只有店长可以索引）
        token, shop_id = parse_authorization(authorization)
        user_context = await verify_token(token, shop_id)

        # 检查权限（只有店长可以索引）
        if user_context.role not in ["店长", "超级管理员"]:
            raise HTTPException(status_code=403, detail="只有店长可以索引文档")

        # 解析文档
        files = parse_directory(request.directory, request.file_types)
        if not files:
            return {"message": "未找到可索引的文档", "count": 0}

        # 分块并存储
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

        # 添加到向量库
        ids = add_documents(all_texts, all_metadatas)

        return {
            "message": "文档索引完成",
            "file_count": len(files),
            "chunk_count": len(ids),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"索引失败: {str(e)}")
