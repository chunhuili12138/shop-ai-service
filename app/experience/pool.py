"""
经验池管理器
支持多 Agent 类型的经验记录、检索、合并、清理
"""

import os
import json
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from langchain_chroma import Chroma
from langchain_core.documents import Document
from app.config import settings
from app.rag.embeddings import get_embeddings
from app.experience.models import Experience, ExperienceType, AgentType
from app.chroma_config import chroma_settings


class ExperiencePool:
    """
    经验池管理器
    
    功能：
    1. 记录成功/失败案例
    2. 向量化检索相似经验
    3. 相似案例合并（更新使用次数）
    4. 定期清理低质量案例
    5. 按使用频率淘汰
    """
    
    def __init__(self):
        self.embeddings = get_embeddings()
        self._vectorstore = None
        self.collection_name = "experience_pool"
    
    @property
    def vectorstore(self) -> Chroma:
        """懒加载向量库"""
        if self._vectorstore is None:
            persist_dir = os.path.join(settings.CHROMA_PERSIST_DIR, "experience")
            os.makedirs(persist_dir, exist_ok=True)
            
            self._vectorstore = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=persist_dir,
                client_settings=chroma_settings,
            )
        return self._vectorstore
    
    async def record_success(
        self, 
        agent_type: str, 
        question: str, 
        solution: str, 
        result_summary: str,
        solving_process: List[Dict[str, Any]] = None,
        metadata: Dict[str, Any] = None
    ) -> str:
        """
        记录成功案例
        
        Args:
            agent_type: Agent 类型（nl2sql/tool/rag/supervisor）
            question: 用户问题
            solution: 解决方案（SQL/工具调用/回答）
            result_summary: 结果摘要
            solving_process: 解决流程（步骤列表）
            metadata: 额外元数据
        
        Returns:
            经验 ID
        """
        try:
            # 检查是否存在相似的成功案例
            similar = await self._find_similar_experience(
                agent_type, question, ExperienceType.SUCCESS
            )
            
            if similar:
                # 合并：更新使用次数和成功次数
                await self._merge_experience(similar.id)
                print(f"[ExperiencePool] 合并成功案例: {similar.id}")
                return similar.id
            
            # 创建新的经验条目
            experience = Experience(
                id=f"exp_{uuid.uuid4().hex[:16]}",
                agent_type=agent_type,
                experience_type=ExperienceType.SUCCESS,
                question=question,
                solution=solution,
                result_summary=result_summary[:500],
                solving_process=solving_process or [],
                metadata=metadata or {},
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                usage_count=1,
                success_count=1,
                quality_score=80,
            )
            
            # 存储到向量库
            await self._store_experience(experience)
            
            print(f"[ExperiencePool] 记录成功案例: {experience.id}")
            return experience.id
        except Exception as e:
            print(f"[ExperiencePool] 记录成功案例失败: {str(e)}")
            return ""
    
    async def record_failure_and_fix(
        self, 
        agent_type: str, 
        question: str,
        error: str, 
        original_solution: str,
        fixed_solution: str = None,
        metadata: Dict[str, Any] = None
    ) -> str:
        """
        记录失败案例和修复
        
        Args:
            agent_type: Agent 类型
            question: 用户问题
            error: 错误信息
            original_solution: 原始解决方案
            fixed_solution: 修复后的方案（如果有）
            metadata: 额外元数据
        
        Returns:
            经验 ID
        """
        try:
            experience = Experience(
                id=f"exp_{uuid.uuid4().hex[:16]}",
                agent_type=agent_type,
                experience_type=ExperienceType.FAILURE_FIX,
                question=question,
                solution=original_solution,
                error=error[:500],
                fixed_solution=fixed_solution or "",
                metadata=metadata or {},
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                usage_count=1,
                success_count=0,
                quality_score=60,
            )
            
            await self._store_experience(experience)
            
            print(f"[ExperiencePool] 记录失败案例: {experience.id}")
            return experience.id
        except Exception as e:
            print(f"[ExperiencePool] 记录失败案例失败: {str(e)}")
            return ""
    
    async def retrieve_similar(
        self, 
        agent_type: str, 
        question: str, 
        k: int = 3,
        experience_type: str = None
    ) -> List[Experience]:
        """
        检索相似经验
        
        Args:
            agent_type: Agent 类型
            question: 用户问题
            k: 返回数量
            experience_type: 过滤类型（可选）
        
        Returns:
            相似经验列表
        """
        try:
            # 构建过滤条件
            filter_dict = {"agent_type": agent_type}
            if experience_type:
                filter_dict["experience_type"] = experience_type
            
            # 向量检索
            results = self.vectorstore.similarity_search_with_score(
                question,
                k=k * 2,  # 多检索一些，后面过滤
                filter=filter_dict
            )
            
            # 转换为 Experience 对象（过滤低相似度结果）
            experiences = []
            # Chroma 的 score 是距离，越小越相似。0.4 以下为高相关，0.4-0.6 为中等相关
            SIMILARITY_THRESHOLD = 0.45
            for doc, score in results[:k * 2]:
                if score > SIMILARITY_THRESHOLD:
                    print(f"[ExperiencePool] 过滤低相似度结果: score={score:.3f}, question={doc.page_content[:50]}")
                    continue
                if len(experiences) >= k:
                    break
                exp_data = doc.metadata.copy()
                exp_data["question"] = doc.page_content
                exp_data["solution"] = doc.metadata.get("solution", "")
                exp_data["result_summary"] = doc.metadata.get("result_summary", "")
                exp_data["error"] = doc.metadata.get("error", "")
                exp_data["fixed_solution"] = doc.metadata.get("fixed_solution", "")
                
                # 解析 solving_process
                solving_process_str = doc.metadata.get("solving_process", "[]")
                try:
                    exp_data["solving_process"] = json.loads(solving_process_str)
                except json.JSONDecodeError:
                    exp_data["solving_process"] = []
                
                exp = Experience.from_dict(exp_data)
                experiences.append(exp)
            
            return experiences
        except Exception as e:
            print(f"[ExperiencePool] 检索经验失败: {str(e)}")
            return []
    
    def format_for_prompt(self, experiences: List[Experience]) -> str:
        """
        将经验格式化为 Prompt
        
        Args:
            experiences: 经验列表
        
        Returns:
            格式化后的文本
        """
        if not experiences:
            return ""
        
        formatted = "## 相似案例参考（来自经验库）\n\n"
        
        success_exps = [e for e in experiences if e.experience_type == ExperienceType.SUCCESS]
        failure_exps = [e for e in experiences if e.experience_type == ExperienceType.FAILURE_FIX]
        
        # 成功案例
        if success_exps:
            formatted += "### 成功案例\n"
            for i, exp in enumerate(success_exps, 1):
                formatted += f"**案例 {i}**（使用次数: {exp.usage_count}）\n"
                formatted += f"问题：{exp.question}\n"
                
                # 显示解决流程
                if exp.solving_process:
                    formatted += "解决流程：\n"
                    for step in exp.solving_process:
                        step_num = step.get("step", "")
                        step_desc = step.get("description", "")
                        step_detail = step.get("detail", "")
                        if step_num and step_desc:
                            formatted += f"  {step_num}. {step_desc}"
                            if step_detail:
                                formatted += f" - {step_detail}"
                            formatted += "\n"
                
                if exp.agent_type == AgentType.NL2SQL:
                    formatted += f"SQL：\n```sql\n{exp.solution}\n```\n"
                elif exp.agent_type == AgentType.TOOL:
                    formatted += f"工具调用：{exp.solution}\n"
                else:
                    formatted += f"回答：{exp.solution[:200]}\n"
                
                formatted += "\n"
        
        # 失败案例（含修复）
        if failure_exps:
            formatted += "### 失败案例（请避免重复错误）\n"
            for i, exp in enumerate(failure_exps, 1):
                formatted += f"**案例 {i}**\n"
                formatted += f"问题：{exp.question}\n"
                formatted += f"错误：{exp.error}\n"
                
                if exp.fixed_solution:
                    formatted += f"修复方案：\n```sql\n{exp.fixed_solution}\n```\n"
                
                formatted += "\n"
        
        return formatted
    
    async def _store_experience(self, experience: Experience):
        """存储经验到向量库"""
        doc = Document(
            page_content=experience.question,
            metadata={
                "id": experience.id,
                "agent_type": experience.agent_type,
                "experience_type": experience.experience_type,
                "solution": experience.solution,
                "result_summary": experience.result_summary,
                "error": experience.error,
                "fixed_solution": experience.fixed_solution,
                "solving_process": json.dumps(experience.solving_process, ensure_ascii=False),
                "created_at": experience.created_at,
                "updated_at": experience.updated_at,
                "usage_count": experience.usage_count,
                "success_count": experience.success_count,
                "quality_score": experience.quality_score,
            }
        )
        self.vectorstore.add_documents([doc], ids=[experience.id])
    
    async def _find_similar_experience(
        self, 
        agent_type: str, 
        question: str,
        experience_type: str,
        threshold: float = 0.9
    ) -> Optional[Experience]:
        """查找相似的经验（用于合并）"""
        try:
            results = self.vectorstore.similarity_search_with_score(
                question,
                k=1,
                filter={
                    "agent_type": agent_type,
                    "experience_type": experience_type,
                }
            )
            
            if results and results[0][1] < (1 - threshold):
                doc, score = results[0]
                exp_data = doc.metadata.copy()
                exp_data["question"] = doc.page_content
                return Experience.from_dict(exp_data)
            
            return None
        except Exception:
            return None
    
    async def _merge_experience(self, experience_id: str):
        """合并经验（更新使用次数）"""
        try:
            results = self.vectorstore.get(ids=[experience_id])
            if results and results.get("metadatas"):
                metadata = results["metadatas"][0]
                metadata["usage_count"] = metadata.get("usage_count", 0) + 1
                metadata["success_count"] = metadata.get("success_count", 0) + 1
                metadata["updated_at"] = datetime.now().isoformat()
                
                # 删除旧的，添加新的
                self.vectorstore.delete(ids=[experience_id])
                self.vectorstore.add_texts(
                    texts=[results["documents"][0]],
                    metadatas=[metadata],
                    ids=[experience_id]
                )
        except Exception as e:
            print(f"[ExperiencePool] 合并经验失败: {str(e)}")
    
    async def cleanup_low_quality(self, min_quality: int = 50, min_usage: int = 2):
        """
        清理低质量案例
        
        Args:
            min_quality: 最低质量评分
            min_usage: 最低使用次数
        """
        try:
            all_experiences = self.vectorstore.get()
            
            if not all_experiences or not all_experiences.get("ids"):
                return
            
            expired_ids = []
            for i, metadata in enumerate(all_experiences.get("metadatas", [])):
                quality = metadata.get("quality_score", 0)
                usage = metadata.get("usage_count", 0)
                
                # 清理条件：质量低且使用次数少
                if quality < min_quality and usage < min_usage:
                    expired_ids.append(all_experiences["ids"][i])
            
            if expired_ids:
                self.vectorstore.delete(ids=expired_ids)
                print(f"[ExperiencePool] 清理低质量案例: {len(expired_ids)} 条")
        except Exception as e:
            print(f"[ExperiencePool] 清理失败: {str(e)}")
    
    async def cleanup_by_frequency(self, max_age_days: int = 30, min_usage: int = 1):
        """
        按频率淘汰（长时间未使用的案例）
        
        Args:
            max_age_days: 最大保留天数
            min_usage: 最低使用次数
        """
        try:
            all_experiences = self.vectorstore.get()
            
            if not all_experiences or not all_experiences.get("ids"):
                return
            
            cutoff_date = datetime.now().timestamp() - (max_age_days * 24 * 60 * 60)
            
            expired_ids = []
            for i, metadata in enumerate(all_experiences.get("metadatas", [])):
                created_at = metadata.get("created_at", "")
                usage = metadata.get("usage_count", 0)
                
                if created_at:
                    try:
                        created_timestamp = datetime.fromisoformat(created_at).timestamp()
                        # 淘汰条件：超过保留天数且使用次数少
                        if created_timestamp < cutoff_date and usage < min_usage:
                            expired_ids.append(all_experiences["ids"][i])
                    except Exception:
                        pass
            
            if expired_ids:
                self.vectorstore.delete(ids=expired_ids)
                print(f"[ExperiencePool] 淘汰过期案例: {len(expired_ids)} 条")
        except Exception as e:
            print(f"[ExperiencePool] 淘汰失败: {str(e)}")


# 全局实例
_experience_pool = None


def get_experience_pool() -> ExperiencePool:
    """获取经验池实例"""
    global _experience_pool
    if _experience_pool is None:
        _experience_pool = ExperiencePool()
    return _experience_pool
