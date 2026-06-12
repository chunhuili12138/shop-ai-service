"""
Redis会话管理模块
支持多轮对话历史存储
"""

import json
from typing import Optional
from datetime import datetime
from redis import Redis
from app.config import settings


class SessionManager:
    """
    会话管理器（Redis存储）
    
    数据结构：
    - Key: rag:session:{session_id}
    - Value: List[JSON] 消息列表
    - TTL: 1小时自动过期
    
    会话隔离：
    - 不同session_id的会话完全隔离
    - A用户的上下文不会串到B用户
    """

    def __init__(self):
        self.redis = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=1,  # 使用db=1存储RAG会话
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
        )
        self.session_ttl = 86400 * 7  # 7天过期（原来1小时太短，会导致会话丢失）

    def get_history(self, session_id: str) -> list[dict]:
        """
        获取对话历史
        
        Args:
            session_id: 会话ID
        
        Returns:
            消息列表 [{"role": "user/assistant", "content": "...", "timestamp": "..."}]
        """
        key = f"rag:session:{session_id}"
        messages = self.redis.lrange(key, 0, -1)
        
        result = []
        for msg in messages:
            try:
                result.append(json.loads(msg))
            except json.JSONDecodeError:
                continue
        
        return result

    def add_message(self, session_id: str, role: str, content: str, **kwargs):
        """
        添加消息到历史
        
        Args:
            session_id: 会话ID
            role: 角色（user/assistant/summary）
            content: 消息内容
            **kwargs: 额外字段（如 data_type, steps 等）
        """
        key = f"rag:session:{session_id}"
        message = {
            "id": f"{session_id}_{datetime.now().timestamp()}",
            "role": role,
            "content": content,
            "timestamp": int(datetime.now().timestamp() * 1000),  # 毫秒时间戳
        }
        # 添加额外字段
        message.update(kwargs)
        
        self.redis.rpush(key, json.dumps(message, ensure_ascii=False))
        self.redis.expire(key, self.session_ttl)

    def get_clarification_count(self, session_id: str) -> int:
        """
        获取当前追问次数
        
        Args:
            session_id: 会话ID
        
        Returns:
            追问次数
        """
        key = f"rag:session:{session_id}:clarification_count"
        count = self.redis.get(key)
        return int(count) if count else 0

    def increment_clarification_count(self, session_id: str) -> int:
        """
        追问次数加1
        
        Args:
            session_id: 会话ID
        
        Returns:
            新的追问次数
        """
        key = f"rag:session:{session_id}:clarification_count"
        count = self.redis.incr(key)
        self.redis.expire(key, self.session_ttl)
        return count

    def reset_clarification_count(self, session_id: str):
        """
        重置追问次数（当用户回答了追问后调用）
        
        Args:
            session_id: 会话ID
        """
        key = f"rag:session:{session_id}:clarification_count"
        self.redis.delete(key)

    def clear_session(self, session_id: str):
        """
        清空会话
        
        Args:
            session_id: 会话ID
        """
        # 清空消息历史
        key = f"rag:session:{session_id}"
        self.redis.delete(key)
        
        # 清空追问次数
        count_key = f"rag:session:{session_id}:clarification_count"
        self.redis.delete(count_key)
        
        # 清空待处理的追问状态
        pending_key = f"rag:session:{session_id}:pending_clarification"
        self.redis.delete(pending_key)

    def save_pending_clarification(
        self, 
        session_id: str, 
        question: str, 
        options: list[str],
        shop_id: int = 5
    ):
        """
        保存待处理的追问状态
        
        当系统追问后，等待用户回答时使用
        
        Args:
            session_id: 会话ID
            question: 原始问题
            options: 追问选项
            shop_id: 店铺ID
        """
        key = f"rag:session:{session_id}:pending_clarification"
        data = json.dumps({
            "original_question": question,
            "options": options,
            "shop_id": shop_id,
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False)
        
        self.redis.set(key, data, ex=self.session_ttl)

    def get_pending_clarification(self, session_id: str) -> Optional[dict]:
        """
        获取待处理的追问状态
        
        Args:
            session_id: 会话ID
        
        Returns:
            待处理的追问信息，如果没有则返回None
        """
        key = f"rag:session:{session_id}:pending_clarification"
        data = self.redis.get(key)
        
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    def clear_pending_clarification(self, session_id: str):
        """
        清除待处理的追问状态
        
        Args:
            session_id: 会话ID
        """
        key = f"rag:session:{session_id}:pending_clarification"
        self.redis.delete(key)

    def session_exists(self, session_id: str) -> bool:
        """
        检查会话是否存在
        
        Args:
            session_id: 会话ID
        
        Returns:
            是否存在
        """
        key = f"rag:session:{session_id}"
        return self.redis.exists(key) > 0

    def create_session(self, session_id: str, user_id: int, title: str = ""):
        """
        创建新会话
        
        Args:
            session_id: 会话ID
            user_id: 用户ID
            title: 会话标题
        """
        # 存储会话元数据
        meta_key = f"rag:session:{session_id}:meta"
        meta = json.dumps({
            "id": session_id,
            "user_id": user_id,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": 0,
        }, ensure_ascii=False)
        self.redis.set(meta_key, meta, ex=self.session_ttl)
        
        # 添加到用户的会话列表
        user_sessions_key = f"rag:user_sessions:{user_id}"
        self.redis.sadd(user_sessions_key, session_id)
        self.redis.expire(user_sessions_key, self.session_ttl)

    def get_user_sessions(self, user_id: int) -> list[dict]:
        """
        获取用户的会话列表
        
        Args:
            user_id: 用户ID
        
        Returns:
            会话列表
        """
        user_sessions_key = f"rag:user_sessions:{user_id}"
        session_ids = self.redis.smembers(user_sessions_key)
        
        sessions = []
        for session_id in session_ids:
            meta_key = f"rag:session:{session_id}:meta"
            meta_data = self.redis.get(meta_key)
            if meta_data:
                try:
                    session = json.loads(meta_data)
                    # 获取消息数量
                    msg_key = f"rag:session:{session_id}"
                    session["message_count"] = self.redis.llen(msg_key)
                    sessions.append(session)
                except json.JSONDecodeError:
                    continue
        
        # 按更新时间排序
        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return sessions

    def update_session(self, session_id: str, **kwargs):
        """
        更新会话信息
        
        Args:
            session_id: 会话ID
            **kwargs: 要更新的字段
        """
        meta_key = f"rag:session:{session_id}:meta"
        meta_data = self.redis.get(meta_key)
        
        if meta_data:
            try:
                meta = json.loads(meta_data)
                meta.update(kwargs)
                meta["updated_at"] = datetime.now().isoformat()
                self.redis.set(meta_key, json.dumps(meta, ensure_ascii=False), ex=self.session_ttl)
            except json.JSONDecodeError:
                pass

    def get_history_for_llm(
        self, 
        session_id: str, 
        max_user_messages: int = 30,
        recent_ai_rounds: int = 5
    ) -> dict:
        """
        获取适合 LLM 的历史消息
        
        策略：
        - 用户消息：完整保留（上限30条）
        - AI回复：最近5轮完整
        - 更早的AI回复：LLM压缩为纪要点
        
        Args:
            session_id: 会话ID
            max_user_messages: 用户消息最大数量
            recent_ai_rounds: 最近保留的AI对话轮数
        
        Returns:
            {
                "summary": str,              # 历史纪要（可能为空）
                "recent_conversations": list, # 最近完整对话
                "total_messages": int         # 总消息数
            }
        """
        all_messages = self.get_history(session_id)
        
        if not all_messages:
            return {
                "summary": "",
                "recent_conversations": [],
                "total_messages": 0
            }
        
        # 分离用户消息、AI回复和纪要
        user_msgs = [m for m in all_messages if m["role"] == "user"]
        ai_msgs = [m for m in all_messages if m["role"] == "assistant"]
        summaries = [m for m in all_messages if m["role"] == "summary"]
        
        # 计算最近对话的起始索引（取最近 N 轮）
        recent_count = recent_ai_rounds * 2  # 每轮包含用户问题+AI回答
        recent_messages = all_messages[-recent_count:] if len(all_messages) > recent_count else all_messages
        
        # 获取或生成历史纪要
        summary = ""
        if summaries:
            # 使用最新的纪要
            summary = summaries[-1]["content"]
        elif len(all_messages) > recent_count:
            # 需要压缩更早的历史
            early_messages = all_messages[:-recent_count]
            summary = self._compress_history(early_messages, session_id)
        
        return {
            "summary": summary,
            "recent_conversations": recent_messages,
            "total_messages": len(all_messages)
        }

    def _compress_history(self, messages: list, session_id: str) -> str:
        """
        使用 LLM 压缩历史消息为纪要
        
        Args:
            messages: 要压缩的消息列表
            session_id: 会话ID（用于保存纪要）
        
        Returns:
            压缩后的纪要文本
        """
        if not messages:
            return ""
        
        # 格式化消息为文本（只处理用户和助手消息，跳过 summary）
        formatted = []
        for msg in messages:
            if msg["role"] == "summary":
                continue  # 跳过已有的纪要
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"][:500]  # 限制单条消息长度
            formatted.append(f"{role}: {content}")
        
        if not formatted:
            return ""
        
        text = "\n".join(formatted)
        
        # 调用 LLM 压缩
        try:
            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage
            
            llm = get_chat_llm()
            prompt = f"""请将以下对话历史压缩为简洁的纪要点，保留关键信息（如查询过的数据、重要结论、待办事项等）。

对话历史：
{text}

要求：
1. 使用要点列表格式（• 开头）
2. 每个要点不超过50字
3. 保留数字、日期、金额等关键数据
4. 保留重要的业务结论和决策
5. 忽略寒暄、确认等无实质内容的对话
6. 最多保留10个要点

纪要："""
            
            result = llm.invoke([HumanMessage(content=prompt)])
            summary = result.content
            
            # 保存纪要到 Redis
            self.add_message(session_id, "summary", summary)
            
            return summary
            
        except Exception as e:
            print(f"[SessionManager] 压缩历史失败: {str(e)}")
            # 压缩失败时返回简化版本
            return f"（历史记录压缩失败，共 {len(messages)} 条消息）"

    def _merge_conversations(self, user_msgs: list, ai_msgs: list) -> list:
        """
        合并用户消息和AI回复为对话列表
        
        Args:
            user_msgs: 用户消息列表
            ai_msgs: AI回复列表
        
        Returns:
            合并后的对话列表
        """
        conversations = []
        
        # 按时间顺序合并
        all_msgs = user_msgs + ai_msgs
        all_msgs.sort(key=lambda x: x.get("timestamp", ""))
        
        for msg in all_msgs:
            conversations.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        
        return conversations


# 全局实例
_session_manager = None


def get_session_manager() -> SessionManager:
    """获取Session Manager单例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
