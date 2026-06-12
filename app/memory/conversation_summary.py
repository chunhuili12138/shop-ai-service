"""
对话摘要模块
自动生成和存储对话摘要
"""

import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from app.config import settings
from app.llm import get_chat_llm
from app.rag.embeddings import get_embeddings
from app.chroma_config import chroma_settings


class ConversationSummaryManager:
    """
    对话摘要管理器
    
    功能：
    - 自动提取对话中的关键信息
    - 生成对话摘要
    - 存储到向量数据库
    - 检索相关摘要
    """
    
    # 摘要生成提示词
    SUMMARY_PROMPT = """请将以下对话总结为简洁的摘要，保留关键信息：

对话内容：
{conversation}

要求：
1. 提取对话的主要话题
2. 记录用户的关键问题和需求
3. 记录获得的重要信息或结论
4. 保持简洁，不超过200字

摘要："""
    
    def __init__(self):
        self.embeddings = get_embeddings()
        self.collection_name = "conversation_summaries"
        self._vectorstore = None
        self._llm = None
    
    @property
    def vectorstore(self) -> Chroma:
        """懒加载向量库"""
        if self._vectorstore is None:
            self._vectorstore = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=settings.CHROMA_PERSIST_DIR,
                client_settings=chroma_settings,
            )
        return self._vectorstore
    
    @property
    def llm(self):
        """懒加载 LLM"""
        if self._llm is None:
            self._llm = get_chat_llm()
        return self._llm
    
    async def summarize(self, messages: List[Dict[str, str]]) -> str:
        """
        使用 LLM 生成对话摘要
        
        Args:
            messages: 对话消息列表
        
        Returns:
            对话摘要
        """
        try:
            # 格式化对话内容
            conversation = self._format_conversation(messages)
            
            # 调用 LLM 生成摘要
            prompt = ChatPromptTemplate.from_template(self.SUMMARY_PROMPT)
            chain = prompt | self.llm
            
            response = await chain.ainvoke({"conversation": conversation})
            return response.content.strip()
        except Exception as e:
            print(f"[ConversationSummary] 生成摘要失败: {str(e)}")
            return ""
    
    async def create_and_store(self, user_id: int, session_id: str, messages: List[Dict[str, str]]):
        """
        生成并存储对话摘要
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            messages: 对话消息列表
        """
        try:
            # 生成摘要
            summary = await self.summarize(messages)
            
            if not summary:
                return
            
            # 提取关键词
            keywords = self._extract_keywords(messages)
            
            # 存储到向量库
            metadata = {
                "user_id": user_id,
                "session_id": session_id,
                "type": "conversation_summary",
                "keywords": json.dumps(keywords, ensure_ascii=False),
                "message_count": len(messages),
                "timestamp": datetime.now().isoformat(),
            }
            
            self.vectorstore.add_texts(
                texts=[summary],
                metadatas=[metadata],
                ids=[f"summary_{session_id}"]
            )
            
            print(f"[ConversationSummary] 存储摘要成功: session_id={session_id}")
        except Exception as e:
            print(f"[ConversationSummary] 存储摘要失败: {str(e)}")
    
    async def get_relevant_summaries(self, user_id: int, query: str, k: int = 3) -> List[str]:
        """
        检索相关对话摘要
        
        Args:
            user_id: 用户ID
            query: 查询内容
            k: 返回数量
        
        Returns:
            摘要列表
        """
        try:
            results = self.vectorstore.similarity_search(
                query=query,
                k=k,
                filter={"user_id": user_id, "type": "conversation_summary"}
            )
            
            return [doc.page_content for doc in results]
        except Exception as e:
            print(f"[ConversationSummary] 检索摘要失败: {str(e)}")
            return []
    
    async def get_user_summaries(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取用户的对话摘要历史
        
        Args:
            user_id: 用户ID
            limit: 返回数量
        
        Returns:
            摘要列表
        """
        try:
            results = self.vectorstore.similarity_search(
                query=f"user {user_id} conversation",
                k=limit,
                filter={"user_id": user_id, "type": "conversation_summary"}
            )
            
            return [
                {
                    "summary": doc.page_content,
                    "session_id": doc.metadata.get("session_id"),
                    "keywords": json.loads(doc.metadata.get("keywords", "[]")),
                    "timestamp": doc.metadata.get("timestamp"),
                }
                for doc in results
            ]
        except Exception as e:
            print(f"[ConversationSummary] 获取用户摘要失败: {str(e)}")
            return []
    
    def _format_conversation(self, messages: List[Dict[str, str]]) -> str:
        """格式化对话内容"""
        formatted = []
        for msg in messages:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = msg.get("content", "")
            if content:
                formatted.append(f"{role}: {content}")
        return "\n".join(formatted)
    
    def _extract_keywords(self, messages: List[Dict[str, str]]) -> List[str]:
        """从对话中提取关键词"""
        keywords = set()
        
        # 关键词列表
        keyword_list = [
            "营收", "顾客", "库存", "套餐", "排班", "报表",
            "优惠券", "评价", "退款", "核销", "员工", "财务",
            "采购", "供应商", "物料", "通知", "考勤"
        ]
        
        for msg in messages:
            content = msg.get("content", "")
            for keyword in keyword_list:
                if keyword in content:
                    keywords.add(keyword)
        
        return list(keywords)
    
    async def delete_summary(self, session_id: str):
        """删除指定会话的摘要"""
        try:
            self.vectorstore.delete(ids=[f"summary_{session_id}"])
            print(f"[ConversationSummary] 删除摘要成功: session_id={session_id}")
        except Exception as e:
            print(f"[ConversationSummary] 删除摘要失败: {str(e)}")


# 全局实例
_conversation_summary_manager = None


def get_conversation_summary_manager() -> ConversationSummaryManager:
    """获取对话摘要管理器单例"""
    global _conversation_summary_manager
    if _conversation_summary_manager is None:
        _conversation_summary_manager = ConversationSummaryManager()
    return _conversation_summary_manager
