"""
RAG Chain
实现完整的检索增强生成流程
"""

from langchain_core.messages import HumanMessage
from app.llm import get_chat_llm
from app.rag.retriever import get_retriever


def format_docs(docs) -> str:
    """格式化检索到的文档"""
    formatted = []
    for i, doc in enumerate(docs, 1):
        formatted.append(f"[{i}] {doc.page_content}")
    return "\n\n".join(formatted)


async def query_with_sources(question: str, history_context: str = "") -> dict:
    """
    带来源的RAG查询
    
    Args:
        question: 用户问题
        history_context: 历史上下文（纪要 + 最近对话）
    
    Returns:
        {
            "answer": str,  # 回答内容
            "sources": list,  # 引用来源
            "confidence": float,  # 置信度
        }
    """
    retriever = get_retriever()
    docs = retriever.invoke(question)
    
    # 格式化上下文
    context = format_docs(docs)
    
    # 构建提示词（包含历史上下文）
    history_section = ""
    if history_context:
        history_section = f"""
【对话历史】
{history_context}
"""
    
    prompt = f"""你是一个专业的店铺智能助手，负责回答关于店铺运营的问题。
{history_section}
【知识库参考】
{context}

【用户问题】
{question}

请根据以上信息回答。如果涉及之前对话中的数据，请准确引用。如果知识库中没有相关信息，请诚实地说不知道，不要编造答案。

请用友好、专业的语气回答："""
    
    # 调用 LLM
    llm = get_chat_llm()
    answer = await llm.ainvoke([HumanMessage(content=prompt)])
    
    # 计算平均置信度（支持新的final_score字段）
    scores = [doc.metadata.get("final_score", 0) for doc in docs]
    avg_score = sum(scores) / len(scores) if scores else 0

    return {
        "answer": answer.content,
        "sources": [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
            }
            for doc in docs
        ],
        "confidence": avg_score,
    }
