"""
审批流程模块
处理需要人工审批的高风险操作
"""

import logging
from enum import Enum
from typing import Optional
from pydantic import BaseModel
from app.hitl.interrupt import interrupt_manager
from app.config import settings

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """操作类型"""
    REFUND = "refund"  # 退款
    DELETE = "delete"  # 删除
    UPDATE_ORDER = "update_order"  # 修改订单
    TRANSFER = "transfer"  # 转账
    APPROVE = "approve"  # 审批


class ApprovalRequest(BaseModel):
    """审批请求"""
    session_id: str
    action_type: ActionType
    action_data: dict
    description: str
    operator_id: int


class ApprovalResponse(BaseModel):
    """审批响应"""
    interrupt_id: str
    status: str
    message: str


def require_approval(
    session_id: str,
    action_type: ActionType,
    action_data: dict,
    description: str,
) -> str:
    """
    请求审批

    创建中断点，等待人工审批

    Returns:
        interrupt_id
    """
    return interrupt_manager.create_interrupt(
        session_id=session_id,
        action_type=action_type.value,
        action_data=action_data,
        description=description,
    )


def approve_request(
    interrupt_id: str,
    approved: bool,
    resolved_by: int,
    comment: str = None,
) -> ApprovalResponse:
    """处理审批"""
    success = interrupt_manager.resolve_interrupt(
        interrupt_id=interrupt_id,
        approved=approved,
        resolved_by=resolved_by,
        comment=comment,
    )

    if not success:
        return ApprovalResponse(
            interrupt_id=interrupt_id,
            status="error",
            message="审批请求不存在或已处理",
        )

    return ApprovalResponse(
        interrupt_id=interrupt_id,
        status="approved" if approved else "rejected",
        message="审批已通过" if approved else "审批已拒绝",
    )


def check_approval_required(action_type: ActionType, amount: float = None) -> bool:
    """
    检查是否需要审批

    规则（阈值从配置读取）：
    - 退款操作：金额 > HITL_REFUND_THRESHOLD 需要审批
    - 删除操作：总是需要审批
    - 修改订单：总是需要审批
    - 转账操作：金额 > HITL_TRANSFER_THRESHOLD 需要审批
    """
    if action_type == ActionType.DELETE:
        return True
    if action_type == ActionType.UPDATE_ORDER:
        return True
    if action_type == ActionType.REFUND and amount and amount > settings.HITL_REFUND_THRESHOLD:
        return True
    if action_type == ActionType.TRANSFER and amount and amount > settings.HITL_TRANSFER_THRESHOLD:
        return True
    return False
