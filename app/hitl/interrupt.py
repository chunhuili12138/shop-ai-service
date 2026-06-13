"""
中断机制
实现Agent执行过程中的中断和恢复
存储后端：Redis（持久化，支持服务重启后恢复）
"""

import json
import uuid
import logging
from typing import Optional
from datetime import datetime
from app.config import settings

logger = logging.getLogger(__name__)

# Redis key 前缀
INTERRUPT_KEY_PREFIX = "hitl:interrupt:"
INTERRUPT_TTL = 86400  # 24 小时过期


def _get_redis():
    """延迟导入 Redis 连接"""
    try:
        import redis
        return redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
        )
    except ImportError:
        logger.warning("redis 未安装，HITL 降级为内存存储")
        return None
    except Exception as e:
        logger.error(f"Redis 连接失败: {e}，HITL 降级为内存存储")
        return None


class InterruptManager:
    """
    中断管理器

    管理Agent执行过程中的中断点，
    用于实现Human-in-the-loop审批流程。
    优先使用 Redis 存储，降级为内存存储。
    """

    def __init__(self):
        self._redis = _get_redis()
        # 降级内存存储
        self._memory_store: dict[str, dict] = {}

    def _is_redis_available(self) -> bool:
        """检查 Redis 是否可用"""
        if self._redis is None:
            return False
        try:
            self._redis.ping()
            return True
        except Exception:
            return False

    def create_interrupt(
        self,
        session_id: str,
        action_type: str,
        action_data: dict,
        description: str,
    ) -> str:
        """
        创建中断点

        Args:
            session_id: 会话ID
            action_type: 操作类型
            action_data: 操作数据
            description: 描述信息

        Returns:
            interrupt_id
        """
        interrupt_id = f"{session_id}_{uuid.uuid4().hex[:8]}"
        data = {
            "interrupt_id": interrupt_id,
            "session_id": session_id,
            "action_type": action_type,
            "action_data": action_data,
            "description": description,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "resolved_at": None,
            "resolved_by": None,
            "resolution": None,
        }

        if self._is_redis_available():
            try:
                key = f"{INTERRUPT_KEY_PREFIX}{interrupt_id}"
                self._redis.setex(key, INTERRUPT_TTL, json.dumps(data, ensure_ascii=False))
                logger.info(f"创建中断点(Redis) - interrupt_id={interrupt_id}")
                return interrupt_id
            except Exception as e:
                logger.error(f"Redis 写入失败，降级为内存存储: {e}")

        # 内存存储降级
        self._memory_store[interrupt_id] = data
        logger.info(f"创建中断点(内存) - interrupt_id={interrupt_id}")
        return interrupt_id

    def get_interrupt(self, interrupt_id: str) -> Optional[dict]:
        """获取中断信息"""
        if self._is_redis_available():
            try:
                key = f"{INTERRUPT_KEY_PREFIX}{interrupt_id}"
                raw = self._redis.get(key)
                if raw:
                    return json.loads(raw)
                return None
            except Exception as e:
                logger.error(f"Redis 读取失败: {e}")

        return self._memory_store.get(interrupt_id)

    def resolve_interrupt(
        self,
        interrupt_id: str,
        approved: bool,
        resolved_by: int,
        comment: str = None,
    ) -> bool:
        """
        解决中断（审批）

        Args:
            interrupt_id: 中断ID
            approved: 是否批准
            resolved_by: 审批人ID
            comment: 审批备注

        Returns:
            是否成功
        """
        interrupt = self.get_interrupt(interrupt_id)
        if not interrupt:
            return False

        interrupt["status"] = "approved" if approved else "rejected"
        interrupt["resolved_at"] = datetime.now().isoformat()
        interrupt["resolved_by"] = resolved_by
        interrupt["resolution"] = comment

        if self._is_redis_available():
            try:
                key = f"{INTERRUPT_KEY_PREFIX}{interrupt_id}"
                self._redis.setex(key, INTERRUPT_TTL, json.dumps(interrupt, ensure_ascii=False))
                logger.info(f"解决中断(Redis) - interrupt_id={interrupt_id}, approved={approved}")
                return True
            except Exception as e:
                logger.error(f"Redis 写入失败: {e}")

        self._memory_store[interrupt_id] = interrupt
        logger.info(f"解决中断(内存) - interrupt_id={interrupt_id}, approved={approved}")
        return True

    def get_pending_interrupts(self, session_id: str = None) -> list[dict]:
        """获取待审批的中断列表"""
        results = []

        if self._is_redis_available():
            try:
                # 扫描所有 interrupt key
                cursor = 0
                while True:
                    cursor, keys = self._redis.scan(
                        cursor, match=f"{INTERRUPT_KEY_PREFIX}*", count=100
                    )
                    for key in keys:
                        raw = self._redis.get(key)
                        if raw:
                            interrupt = json.loads(raw)
                            if interrupt.get("status") == "pending":
                                if session_id is None or interrupt.get("session_id") == session_id:
                                    results.append(interrupt)
                    if cursor == 0:
                        break
                return results
            except Exception as e:
                logger.error(f"Redis 扫描失败: {e}")

        # 内存存储降级
        for iid, interrupt in self._memory_store.items():
            if interrupt.get("status") == "pending":
                if session_id is None or interrupt.get("session_id") == session_id:
                    results.append({"interrupt_id": iid, **interrupt})
        return results


# 全局中断管理器实例
interrupt_manager = InterruptManager()
