"""
记忆管理器 - 统一管理用户画像、对话摘要和长期记忆
提供对话前/后钩子，自动更新记忆
"""

import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime
from app.memory.user_profile import UserProfileManager, get_user_profile_manager
from app.memory.conversation_summary import ConversationSummaryManager, get_conversation_summary_manager
from app.memory.long_term_memory import LongTermMemoryManager, get_long_term_memory_manager
from app.config import settings


class MemoryManager:
    """
    记忆管理器 - 统一管理所有记忆模块
    
    功能：
    1. 对话前：检索相关记忆，注入上下文
    2. 对话后：更新用户画像，生成对话摘要
    3. 长期记忆：存储和检索事实、经验、偏好
    """
    
    def __init__(self):
        self.user_profile = get_user_profile_manager()
        self.conversation_summary = get_conversation_summary_manager()
        self.long_term_memory = get_long_term_memory_manager()
        self.enabled = settings.MEMORY_ENABLED if hasattr(settings, 'MEMORY_ENABLED') else True
    
    async def on_conversation_start(self, user_id: int, query: str, shop_id: int = None) -> str:
        """
        对话开始时调用
        检索相关记忆，返回上下文
        
        Args:
            user_id: 用户ID
            query: 用户查询
            shop_id: 店铺ID（可选）
        
        Returns:
            相关记忆上下文
        """
        if not self.enabled:
            return ""
        
        try:
            context_parts = []
            
            # 1. 获取用户画像
            profile = await self.user_profile.get_profile(user_id)
            if profile:
                preferences = profile.get("preferences", [])
                if preferences:
                    context_parts.append(f"用户偏好：{', '.join(preferences)}")
            
            # 2. 检索相关对话摘要
            summaries = await self.conversation_summary.get_relevant_summaries(
                user_id=user_id,
                query=query,
                k=2
            )
            if summaries:
                context_parts.append(f"历史对话摘要：{'；'.join(summaries[:2])}")
            
            # 3. 检索相关长期记忆
            memories = await self.long_term_memory.retrieve(
                query=query,
                user_id=user_id,
                top_k=3
            )
            if memories:
                memory_contents = [m["content"] for m in memories[:2]]
                context_parts.append(f"相关记忆：{'；'.join(memory_contents)}")
            
            # 4. 检索店铺相关事实
            if shop_id:
                facts = await self.long_term_memory.get_facts(
                    query=query,
                    shop_id=shop_id,
                    top_k=2
                )
                if facts:
                    fact_contents = [f["content"] for f in facts[:1]]
                    context_parts.append(f"店铺相关信息：{'；'.join(fact_contents)}")
            
            return "\n".join(context_parts) if context_parts else ""
        except Exception as e:
            print(f"[MemoryManager] 对话前处理失败: {str(e)}")
            return ""
    
    async def on_conversation_end(self, user_id: int, session_id: str, messages: List[Dict[str, str]], shop_id: int = None):
        """
        对话结束时调用
        异步更新用户画像和对话摘要
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            messages: 对话消息列表
            shop_id: 店铺ID（可选）
        """
        if not self.enabled:
            return
        
        try:
            # 异步更新用户画像
            asyncio.create_task(
                self._update_user_profile(user_id, messages)
            )
            
            # 异步生成对话摘要
            asyncio.create_task(
                self._create_conversation_summary(user_id, session_id, messages)
            )
            
            # 异步提取并存储事实
            if shop_id:
                asyncio.create_task(
                    self._extract_and_store_facts(user_id, shop_id, messages)
                )
            
            print(f"[MemoryManager] 对话后处理已启动: user_id={user_id}, session_id={session_id}")
        except Exception as e:
            print(f"[MemoryManager] 对话后处理失败: {str(e)}")
    
    async def _update_user_profile(self, user_id: int, messages: List[Dict[str, str]]):
        """更新用户画像"""
        try:
            await self.user_profile.update_from_conversation(user_id, messages)
            print(f"[MemoryManager] 用户画像更新完成: user_id={user_id}")
        except Exception as e:
            print(f"[MemoryManager] 更新用户画像失败: {str(e)}")
    
    async def _create_conversation_summary(self, user_id: int, session_id: str, messages: List[Dict[str, str]]):
        """生成对话摘要"""
        try:
            await self.conversation_summary.create_and_store(user_id, session_id, messages)
            print(f"[MemoryManager] 对话摘要生成完成: session_id={session_id}")
        except Exception as e:
            print(f"[MemoryManager] 生成对话摘要失败: {str(e)}")
    
    async def _extract_and_store_facts(self, user_id: int, shop_id: int, messages: List[Dict[str, str]]):
        """从对话中提取并存储事实"""
        try:
            # 提取助手回复中的有价值信息
            for msg in messages:
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    # 判断是否包含有价值的事实信息
                    if self._is_valuable_fact(content):
                        await self.long_term_memory.store_fact(
                            content=content,
                            user_id=user_id,
                            shop_id=shop_id,
                            tags=["auto_extracted"]
                        )
        except Exception as e:
            print(f"[MemoryManager] 提取事实失败: {str(e)}")
    
    def _is_valuable_fact(self, content: str) -> bool:
        """判断内容是否是有价值的事实"""
        # 关键词列表
        valuable_keywords = [
            "价格", "套餐", "营业时间", "地址", "电话",
            "规则", "政策", "优惠", "活动", "说明"
        ]
        
        # 检查是否包含关键词
        for keyword in valuable_keywords:
            if keyword in content:
                # 内容长度检查（太短的可能是闲聊）
                if len(content) > 50:
                    return True
        
        return False
    
    # ========== 长期记忆操作 ==========
    
    async def store_memory(self, content: str, memory_type: str, user_id: int = None, **kwargs) -> str:
        """
        存储记忆
        
        Args:
            content: 记忆内容
            memory_type: 记忆类型（fact/experience/preference）
            user_id: 用户ID（可选）
            **kwargs: 其他元数据
        
        Returns:
            记忆ID
        """
        if memory_type == "fact":
            return await self.long_term_memory.store_fact(
                content=content,
                user_id=user_id,
                shop_id=kwargs.get("shop_id"),
                tags=kwargs.get("tags")
            )
        elif memory_type == "experience":
            return await self.long_term_memory.store_experience(
                content=content,
                user_id=user_id,
                context=kwargs.get("context")
            )
        elif memory_type == "preference":
            return await self.long_term_memory.store_preference(
                content=content,
                user_id=user_id,
                preference_type=kwargs.get("preference_type")
            )
        else:
            return await self.long_term_memory.store(content, {"type": memory_type, "user_id": user_id, **kwargs})
    
    async def search_memory(self, query: str, user_id: int = None, memory_type: str = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        搜索记忆
        
        Args:
            query: 查询内容
            user_id: 用户ID（可选）
            memory_type: 记忆类型（可选）
            top_k: 返回数量
        
        Returns:
            记忆列表
        """
        return await self.long_term_memory.retrieve(
            query=query,
            user_id=user_id,
            memory_type=memory_type,
            top_k=top_k
        )
    
    async def forget_memory(self, memory_id: str):
        """遗忘记忆"""
        await self.long_term_memory.forget(memory_id)
    
    async def get_user_context(self, user_id: int) -> Dict[str, Any]:
        """
        获取用户完整上下文
        
        Args:
            user_id: 用户ID
        
        Returns:
            用户上下文（画像、偏好、最近摘要）
        """
        try:
            # 获取用户画像
            profile = await self.user_profile.get_profile(user_id) or {}
            
            # 获取用户偏好
            preferences = await self.long_term_memory.get_preferences(user_id)
            
            # 获取最近对话摘要
            summaries = await self.conversation_summary.get_user_summaries(user_id, limit=5)
            
            return {
                "profile": profile,
                "preferences": [p["content"] for p in preferences],
                "recent_summaries": [s["summary"] for s in summaries],
            }
        except Exception as e:
            print(f"[MemoryManager] 获取用户上下文失败: {str(e)}")
            return {}


# 全局实例
_memory_manager = None


def get_memory_manager() -> MemoryManager:
    """获取记忆管理器单例"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
