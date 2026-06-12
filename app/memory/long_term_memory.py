"""
长期记忆管理模块
存储和检索长期记忆（事实、经验、偏好）
"""

import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from langchain_chroma import Chroma
from app.config import settings
from app.rag.embeddings import get_embeddings
from app.chroma_config import chroma_settings


class LongTermMemoryManager:
    """
    长期记忆管理器
    
    记忆类型：
    - 事实记忆：店铺信息、套餐信息、规则
    - 经验记忆：成功案例、解决方案
    - 偏好记忆：用户偏好、习惯
    """
    
    def __init__(self):
        self.embeddings = get_embeddings()
        self.collection_name = "long_term_memory"
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
    
    async def store(self, content: str, metadata: Dict[str, Any]) -> str:
        """
        存储记忆
        
        Args:
            content: 记忆内容
            metadata: 元数据（必须包含 type 字段）
        
        Returns:
            记忆ID
        """
        try:
            # 生成唯一 ID
            memory_id = f"memory_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            
            # 添加默认元数据
            metadata.update({
                "type": metadata.get("type", "long_term_memory"),
                "created_at": datetime.now().isoformat(),
                "access_count": 0,
            })
            
            self.vectorstore.add_texts(
                texts=[content],
                metadatas=[metadata],
                ids=[memory_id]
            )
            
            print(f"[LongTermMemory] 存储记忆成功: id={memory_id}")
            return memory_id
        except Exception as e:
            print(f"[LongTermMemory] 存储记忆失败: {str(e)}")
            return ""
    
    async def retrieve(self, query: str, user_id: int = None, memory_type: str = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        检索相关记忆
        
        Args:
            query: 查询内容
            user_id: 用户ID（可选，用于过滤）
            memory_type: 记忆类型（可选，用于过滤）
            top_k: 返回数量
        
        Returns:
            记忆列表
        """
        try:
            # 构建过滤条件
            filter_dict = {}
            if user_id:
                filter_dict["user_id"] = user_id
            if memory_type:
                filter_dict["type"] = memory_type
            
            # 执行搜索
            results = self.vectorstore.similarity_search_with_score(
                query=query,
                k=top_k,
                filter=filter_dict if filter_dict else None
            )
            
            # 格式化结果
            memories = []
            for doc, score in results:
                memory = {
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": score,
                }
                memories.append(memory)
                
                # 更新访问计数
                self._update_access_count(doc.metadata.get("id"))
            
            return memories
        except Exception as e:
            print(f"[LongTermMemory] 检索记忆失败: {str(e)}")
            return []
    
    async def get_by_id(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取记忆
        
        Args:
            memory_id: 记忆ID
        
        Returns:
            记忆数据
        """
        try:
            results = self.vectorstore.get(ids=[memory_id])
            
            if results and results.get("ids"):
                return {
                    "id": results["ids"][0],
                    "content": results["documents"][0] if results.get("documents") else "",
                    "metadata": results["metadatas"][0] if results.get("metadatas") else {},
                }
            return None
        except Exception as e:
            print(f"[LongTermMemory] 获取记忆失败: {str(e)}")
            return None
    
    async def update(self, memory_id: str, content: str = None, metadata: Dict[str, Any] = None):
        """
        更新记忆
        
        Args:
            memory_id: 记忆ID
            content: 新内容（可选）
            metadata: 新元数据（可选）
        """
        try:
            # 获取现有记忆
            existing = await self.get_by_id(memory_id)
            if not existing:
                print(f"[LongTermMemory] 记忆不存在: {memory_id}")
                return
            
            # 更新内容
            new_content = content if content is not None else existing["content"]
            new_metadata = existing["metadata"]
            if metadata:
                new_metadata.update(metadata)
            new_metadata["updated_at"] = datetime.now().isoformat()
            
            # 删除旧的，添加新的
            self.vectorstore.delete(ids=[memory_id])
            self.vectorstore.add_texts(
                texts=[new_content],
                metadatas=[new_metadata],
                ids=[memory_id]
            )
            
            print(f"[LongTermMemory] 更新记忆成功: {memory_id}")
        except Exception as e:
            print(f"[LongTermMemory] 更新记忆失败: {str(e)}")
    
    async def forget(self, memory_id: str):
        """
        遗忘（删除）记忆
        
        Args:
            memory_id: 记忆ID
        """
        try:
            self.vectorstore.delete(ids=[memory_id])
            print(f"[LongTermMemory] 遗忘记忆成功: {memory_id}")
        except Exception as e:
            print(f"[LongTermMemory] 遗忘记忆失败: {str(e)}")
    
    async def store_fact(self, content: str, user_id: int = None, shop_id: int = None, tags: List[str] = None) -> str:
        """
        存储事实记忆
        
        Args:
            content: 事实内容
            user_id: 用户ID（可选）
            shop_id: 店铺ID（可选）
            tags: 标签列表（可选）
        
        Returns:
            记忆ID
        """
        metadata = {
            "type": "fact",
            "category": "knowledge",
        }
        if user_id:
            metadata["user_id"] = user_id
        if shop_id:
            metadata["shop_id"] = shop_id
        if tags:
            metadata["tags"] = json.dumps(tags, ensure_ascii=False)
        
        return await self.store(content, metadata)
    
    async def store_experience(self, content: str, user_id: int, context: str = None) -> str:
        """
        存储经验记忆
        
        Args:
            content: 经验内容
            user_id: 用户ID
            context: 上下文（可选）
        
        Returns:
            记忆ID
        """
        metadata = {
            "type": "experience",
            "user_id": user_id,
        }
        if context:
            metadata["context"] = context
        
        return await self.store(content, metadata)
    
    async def store_preference(self, content: str, user_id: int, preference_type: str = None) -> str:
        """
        存储偏好记忆
        
        Args:
            content: 偏好内容
            user_id: 用户ID
            preference_type: 偏好类型（可选）
        
        Returns:
            记忆ID
        """
        metadata = {
            "type": "preference",
            "user_id": user_id,
        }
        if preference_type:
            metadata["preference_type"] = preference_type
        
        return await self.store(content, metadata)
    
    async def get_facts(self, query: str, shop_id: int = None, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        检索事实记忆
        
        Args:
            query: 查询内容
            shop_id: 店铺ID（可选）
            top_k: 返回数量
        
        Returns:
            事实列表
        """
        filter_dict = {"type": "fact"}
        if shop_id:
            filter_dict["shop_id"] = shop_id
        
        return await self.retrieve(query, memory_type="fact", top_k=top_k)
    
    async def get_experiences(self, query: str, user_id: int, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        检索经验记忆
        
        Args:
            query: 查询内容
            user_id: 用户ID
            top_k: 返回数量
        
        Returns:
            经验列表
        """
        return await self.retrieve(query, user_id=user_id, memory_type="experience", top_k=top_k)
    
    async def get_preferences(self, user_id: int) -> List[Dict[str, Any]]:
        """
        获取用户偏好
        
        Args:
            user_id: 用户ID
        
        Returns:
            偏好列表
        """
        return await self.retrieve(
            query=f"user preferences {user_id}",
            user_id=user_id,
            memory_type="preference",
            top_k=10
        )
    
    def _update_access_count(self, memory_id: str):
        """更新访问计数"""
        try:
            if memory_id:
                # 这里简化处理，实际应该更新数据库
                pass
        except Exception:
            pass
    
    async def cleanup_old_memories(self, days: int = 90):
        """
        清理过期记忆
        
        Args:
            days: 保留天数
        """
        try:
            # 获取所有记忆
            all_memories = self.vectorstore.get()
            
            if not all_memories or not all_memories.get("ids"):
                return
            
            # 计算过期时间
            cutoff_date = datetime.now().timestamp() - (days * 24 * 60 * 60)
            
            # 找出过期的记忆
            expired_ids = []
            for i, metadata in enumerate(all_memories.get("metadatas", [])):
                created_at = metadata.get("created_at", "")
                if created_at:
                    try:
                        created_timestamp = datetime.fromisoformat(created_at).timestamp()
                        if created_timestamp < cutoff_date:
                            expired_ids.append(all_memories["ids"][i])
                    except Exception:
                        pass
            
            # 删除过期记忆
            if expired_ids:
                self.vectorstore.delete(ids=expired_ids)
                print(f"[LongTermMemory] 清理过期记忆: {len(expired_ids)} 条")
        except Exception as e:
            print(f"[LongTermMemory] 清理记忆失败: {str(e)}")


# 全局实例
_long_term_memory_manager = None


def get_long_term_memory_manager() -> LongTermMemoryManager:
    """获取长期记忆管理器单例"""
    global _long_term_memory_manager
    if _long_term_memory_manager is None:
        _long_term_memory_manager = LongTermMemoryManager()
    return _long_term_memory_manager
