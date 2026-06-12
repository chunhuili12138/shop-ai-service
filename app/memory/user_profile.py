"""
用户画像存储模块
使用 Chroma 向量库存储用户画像和行为数据
"""

import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from langchain_chroma import Chroma
from langchain_core.documents import Document
from app.config import settings
from app.rag.embeddings import get_embeddings
from app.chroma_config import chroma_settings


class UserProfileManager:
    """
    用户画像管理器
    
    存储内容：
    - 基本信息：姓名、角色、偏好
    - 行为模式：常用查询、访问时间
    - 历史记录：重要操作
    """
    
    def __init__(self):
        self.embeddings = get_embeddings()
        self.collection_name = "user_profiles"
        self._vectorstore = None
    
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
    
    async def get_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        获取用户画像
        
        Args:
            user_id: 用户ID
        
        Returns:
            用户画像字典，不存在返回 None
        """
        try:
            results = self.vectorstore.similarity_search(
                query=f"user profile {user_id}",
                k=1,
                filter={"user_id": user_id, "type": "user_profile"}
            )
            
            if results and results[0].metadata:
                metadata = results[0].metadata
                return {
                    "user_id": metadata.get("user_id"),
                    "name": metadata.get("name", ""),
                    "role": metadata.get("role", ""),
                    "preferences": json.loads(metadata.get("preferences", "[]")),
                    "query_history": json.loads(metadata.get("query_history", "[]")),
                    "last_active": metadata.get("last_active", ""),
                    "updated_at": metadata.get("updated_at", ""),
                }
            return None
        except Exception as e:
            print(f"[UserProfile] 获取画像失败: {str(e)}")
            return None
    
    async def update_profile(self, user_id: int, profile: Dict[str, Any]):
        """
        更新用户画像
        
        Args:
            user_id: 用户ID
            profile: 用户画像数据
        """
        try:
            # 删除旧的画像
            self._delete_by_user_id(user_id, "user_profile")
            
            # 添加新的画像
            metadata = {
                "user_id": user_id,
                "type": "user_profile",
                "name": profile.get("name", ""),
                "role": profile.get("role", ""),
                "preferences": json.dumps(profile.get("preferences", []), ensure_ascii=False),
                "query_history": json.dumps(profile.get("query_history", []), ensure_ascii=False),
                "last_active": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            
            text = f"用户画像: {profile.get('name', '未知')}, 角色: {profile.get('role', '未知')}"
            
            self.vectorstore.add_texts(
                texts=[text],
                metadatas=[metadata],
                ids=[f"profile_{user_id}"]
            )
            
            print(f"[UserProfile] 更新画像成功: user_id={user_id}")
        except Exception as e:
            print(f"[UserProfile] 更新画像失败: {str(e)}")
    
    async def update_from_conversation(self, user_id: int, messages: List[Dict[str, str]]):
        """
        从对话中更新用户画像
        
        Args:
            user_id: 用户ID
            messages: 对话消息列表
        """
        try:
            # 获取现有画像
            profile = await self.get_profile(user_id) or {}
            
            # 提取查询历史
            query_history = profile.get("query_history", [])
            for msg in messages:
                if msg.get("role") == "user":
                    query = msg.get("content", "")
                    if query and query not in query_history:
                        query_history.append(query)
            
            # 只保留最近 20 条查询
            query_history = query_history[-20:]
            
            # 提取偏好（从查询中推断）
            preferences = self._extract_preferences(messages)
            
            # 更新画像
            profile.update({
                "query_history": query_history,
                "preferences": preferences,
                "last_active": datetime.now().isoformat(),
            })
            
            await self.update_profile(user_id, profile)
        except Exception as e:
            print(f"[UserProfile] 从对话更新画像失败: {str(e)}")
    
    def _extract_preferences(self, messages: List[Dict[str, str]]) -> List[str]:
        """从对话中提取用户偏好"""
        preferences = set()
        
        # 关键词映射
        keyword_map = {
            "营收": "关注营收数据",
            "顾客": "关注顾客管理",
            "库存": "关注库存管理",
            "套餐": "关注套餐信息",
            "排班": "关注员工排班",
            "报表": "关注数据报表",
            "优惠券": "关注营销活动",
        }
        
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                for keyword, preference in keyword_map.items():
                    if keyword in content:
                        preferences.add(preference)
        
        return list(preferences)
    
    def _delete_by_user_id(self, user_id: int, doc_type: str):
        """删除指定用户的文档"""
        try:
            # Chroma 不支持直接按 filter 删除，需要获取 ID 后删除
            results = self.vectorstore.get(
                where={"user_id": user_id, "type": doc_type}
            )
            if results and results.get("ids"):
                self.vectorstore.delete(ids=results["ids"])
        except Exception as e:
            print(f"[UserProfile] 删除旧数据失败: {str(e)}")
    
    async def add_behavior(self, user_id: int, behavior_type: str, content: str):
        """
        记录用户行为
        
        Args:
            user_id: 用户ID
            behavior_type: 行为类型（query/action等）
            content: 行为内容
        """
        try:
            metadata = {
                "user_id": user_id,
                "type": "user_behavior",
                "behavior_type": behavior_type,
                "timestamp": datetime.now().isoformat(),
            }
            
            self.vectorstore.add_texts(
                texts=[content],
                metadatas=[metadata]
            )
        except Exception as e:
            print(f"[UserProfile] 记录行为失败: {str(e)}")
    
    async def get_behaviors(self, user_id: int, behavior_type: str = None, limit: int = 10) -> List[Dict]:
        """
        获取用户行为历史
        
        Args:
            user_id: 用户ID
            behavior_type: 行为类型（可选）
            limit: 返回数量
        
        Returns:
            行为列表
        """
        try:
            filter_dict = {"user_id": user_id, "type": "user_behavior"}
            if behavior_type:
                filter_dict["behavior_type"] = behavior_type
            
            results = self.vectorstore.similarity_search(
                query=f"user behavior {user_id}",
                k=limit,
                filter=filter_dict
            )
            
            return [
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata
                }
                for doc in results
            ]
        except Exception as e:
            print(f"[UserProfile] 获取行为历史失败: {str(e)}")
            return []


# 全局实例
_user_profile_manager = None


def get_user_profile_manager() -> UserProfileManager:
    """获取用户画像管理器单例"""
    global _user_profile_manager
    if _user_profile_manager is None:
        _user_profile_manager = UserProfileManager()
    return _user_profile_manager
