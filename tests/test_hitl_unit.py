"""
hitl/interrupt.py 单元测试
测试中断管理器的内存存储模式
"""

import pytest
from unittest.mock import patch
from app.hitl.interrupt import InterruptManager


class TestInterruptManagerMemory:
    """内存模式下的中断管理器测试"""

    def setup_method(self):
        """每个测试前创建新的管理器，强制使用内存模式"""
        self.manager = InterruptManager()
        self.manager._redis = None  # 强制使用内存模式

    def test_create_interrupt(self):
        """创建中断点"""
        interrupt_id = self.manager.create_interrupt(
            session_id="sess-001",
            action_type="refund",
            action_data={"amount": 150},
            description="退款150元",
        )

        assert interrupt_id is not None
        assert "sess-001" in interrupt_id
        assert len(interrupt_id) > 10  # UUID 格式

    def test_get_interrupt(self):
        """获取中断信息"""
        interrupt_id = self.manager.create_interrupt(
            session_id="sess-002",
            action_type="delete",
            action_data={"target": "item-1"},
            description="删除物品",
        )

        result = self.manager.get_interrupt(interrupt_id)

        assert result is not None
        assert result["session_id"] == "sess-002"
        assert result["action_type"] == "delete"
        assert result["status"] == "pending"

    def test_get_nonexistent_interrupt(self):
        """获取不存在的中断"""
        result = self.manager.get_interrupt("nonexistent-id")
        assert result is None

    def test_resolve_interrupt_approve(self):
        """审批通过"""
        interrupt_id = self.manager.create_interrupt(
            session_id="sess-003",
            action_type="refund",
            action_data={"amount": 200},
            description="退款200元",
        )

        success = self.manager.resolve_interrupt(
            interrupt_id=interrupt_id,
            approved=True,
            resolved_by=1,
            comment="同意退款",
        )

        assert success is True

        result = self.manager.get_interrupt(interrupt_id)
        assert result["status"] == "approved"
        assert result["resolved_by"] == 1
        assert result["resolution"] == "同意退款"

    def test_resolve_interrupt_reject(self):
        """审批拒绝"""
        interrupt_id = self.manager.create_interrupt(
            session_id="sess-004",
            action_type="transfer",
            action_data={"amount": 5000},
            description="转账5000元",
        )

        success = self.manager.resolve_interrupt(
            interrupt_id=interrupt_id,
            approved=False,
            resolved_by=2,
            comment="金额过大",
        )

        assert success is True

        result = self.manager.get_interrupt(interrupt_id)
        assert result["status"] == "rejected"

    def test_resolve_nonexistent_interrupt(self):
        """解决不存在的中断"""
        success = self.manager.resolve_interrupt(
            interrupt_id="nonexistent",
            approved=True,
            resolved_by=1,
        )
        assert success is False

    def test_get_pending_interrupts(self):
        """获取待审批列表"""
        self.manager.create_interrupt("s1", "refund", {}, "退款1")
        self.manager.create_interrupt("s2", "delete", {}, "删除1")

        # 解决第一个
        pending = self.manager.get_pending_interrupts()
        assert len(pending) == 2

        self.manager.resolve_interrupt(pending[0]["interrupt_id"], True, 1)

        pending = self.manager.get_pending_interrupts()
        assert len(pending) == 1

    def test_get_pending_interrupts_by_session(self):
        """按会话过滤待审批列表"""
        self.manager.create_interrupt("s1", "refund", {}, "退款1")
        self.manager.create_interrupt("s2", "delete", {}, "删除1")

        pending = self.manager.get_pending_interrupts(session_id="s1")
        assert len(pending) == 1
        assert pending[0]["session_id"] == "s1"

    def test_interrupt_id_uniqueness(self):
        """中断 ID 唯一性"""
        ids = set()
        for _ in range(100):
            interrupt_id = self.manager.create_interrupt("s1", "test", {}, "test")
            ids.add(interrupt_id)

        assert len(ids) == 100
