"""
中断机制
实现Agent执行过程中的中断和恢复
"""

import json
from typing import Optional
from datetime import datetime
from app.config import settings


class InterruptManager:
    """
    中断管理器
    
    管理Agent执行过程中的中断点，
    用于实现Human-in-the-loop审批流程
    """

    def __init__(self):
        # 使用内存存储（生产环境应使用Redis）
        self._interrupts: dict[str, dict] = {}

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
        interrupt_id = f"{session_id}_{datetime.now().timestamp()}"
        self._interrupts[interrupt_id] = {
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
        return interrupt_id

    def get_interrupt(self, interrupt_id: str) -> Optional[dict]:
        """获取中断信息"""
        return self._interrupts.get(interrupt_id)

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
        interrupt = self._interrupts.get(interrupt_id)
        if not interrupt:
            return False

        interrupt["status"] = "approved" if approved else "rejected"
        interrupt["resolved_at"] = datetime.now().isoformat()
        interrupt["resolved_by"] = resolved_by
        interrupt["resolution"] = comment
        return True

    def get_pending_interrupts(self, session_id: str = None) -> list[dict]:
        """获取待审批的中断列表"""
        results = []
        for iid, interrupt in self._interrupts.items():
            if interrupt["status"] == "pending":
                if session_id is None or interrupt["session_id"] == session_id:
                    results.append({"interrupt_id": iid, **interrupt})
        return results


# 全局中断管理器实例
interrupt_manager = InterruptManager()
