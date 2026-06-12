"""
交易查询和操作工具
使用 Pydantic V2 Schema 约束入参，LangChain StructuredTool 注册
"""

from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql


# ==================== Input Schemas ====================

class PurchasesQueryInput(BaseModel):
    """购买记录查询参数"""
    shop_id: int = Field(description="店铺ID")
    customer_id: Optional[int] = Field(default=None, description="顾客ID（可选）")
    status: Optional[str] = Field(
        default=None,
        description="状态筛选: valid=有效, refunded=已退款, expired=已过期（可选）"
    )
    limit: int = Field(default=10, description="返回数量，默认10")


class GameSessionsQueryInput(BaseModel):
    """核销记录查询参数"""
    shop_id: int = Field(description="店铺ID")
    customer_id: Optional[int] = Field(default=None, description="顾客ID（可选）")
    status: Optional[str] = Field(
        default=None,
        description="状态筛选: active=进行中, finished=已结束（可选）"
    )
    limit: int = Field(default=10, description="返回数量，默认10")


class RefundsQueryInput(BaseModel):
    """退款记录查询参数"""
    shop_id: int = Field(description="店铺ID")
    purchase_id: Optional[int] = Field(default=None, description="购买记录ID（可选）")
    status: Optional[str] = Field(
        default=None,
        description="状态筛选: pending=处理中, approved=已批准, rejected=已拒绝（可选）"
    )
    limit: int = Field(default=10, description="返回数量，默认10")


class RefundApproveInput(BaseModel):
    """退款审批参数"""
    shop_id: int = Field(description="店铺ID")
    refund_id: int = Field(description="退款记录ID")
    remark: Optional[str] = Field(default=None, description="审批备注（可选）")


class RefundRejectInput(BaseModel):
    """退款拒绝参数"""
    shop_id: int = Field(description="店铺ID")
    refund_id: int = Field(description="退款记录ID")
    reason: str = Field(description="拒绝原因")


class GameSessionCheckinInput(BaseModel):
    """核销操作参数"""
    shop_id: int = Field(description="店铺ID")
    customer_id: int = Field(description="顾客ID")
    customer_session_id: int = Field(description="顾客场次ID")


class GameSessionFinishInput(BaseModel):
    """结束游玩参数"""
    shop_id: int = Field(description="店铺ID")
    game_session_id: int = Field(description="游戏场次ID")


# ==================== Tools ====================

@tool(args_schema=PurchasesQueryInput)
def query_purchases(shop_id: int, customer_id: Optional[int] = None, status: Optional[str] = None, limit: int = 10) -> str:
    """
    查询购买记录。
    支持按顾客ID和状态筛选，返回套餐名称、金额、状态和购买时间。
    """
    sql = """
        SELECT
            pu.id,
            pu.customer_id,
            c.nickname as customer_name,
            p.name as package_name,
            pu.total_amount,
            pu.paid_amount,
            pu.status,
            pu.created_at
        FROM purchases pu
        JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        WHERE pu.shop_id = :shop_id
    """

    params = {"shop_id": shop_id, "limit": limit}

    if customer_id:
        sql += " AND pu.customer_id = :customer_id"
        params["customer_id"] = customer_id

    if status:
        status_map = {"valid": 1, "refunded": 2, "expired": 3}
        if status in status_map:
            sql += " AND pu.status = :status"
            params["status"] = status_map[status]

    sql += " ORDER BY pu.created_at DESC LIMIT :limit"

    try:
        results = execute_sql(sql, params)
        if not results:
            return "暂无购买记录"

        status_names = {1: "有效", 2: "已退款", 3: "已过期"}
        output = "购买记录:\n"
        for row in results:
            status_name = status_names.get(row["status"], "未知")
            customer = row["customer_name"] or "未知顾客"
            package = row['package_name']
            amount = row['paid_amount']
            time = row['created_at']
            output += f"- {customer}: {package} ¥{amount:.2f}（{status_name}）- {time}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=GameSessionsQueryInput)
def query_game_sessions(shop_id: int, customer_id: Optional[int] = None, status: Optional[str] = None, limit: int = 10) -> str:
    """
    查询核销/游玩记录。
    支持按顾客ID和状态筛选，返回顾客、套餐、开始结束时间和状态。
    """
    sql = """
        SELECT
            gs.id,
            gs.customer_session_id,
            c.nickname as customer_name,
            p.name as package_name,
            s.name as staff_name,
            gs.start_time,
            gs.end_time,
            gs.status
        FROM game_sessions gs
        LEFT JOIN customer_sessions cs ON gs.customer_session_id = cs.id
        LEFT JOIN purchases pu ON cs.purchase_id = pu.id
        LEFT JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        LEFT JOIN staff s ON gs.staff_id = s.id
        WHERE gs.shop_id = :shop_id
    """

    params = {"shop_id": shop_id, "limit": limit}

    if customer_id:
        sql += " AND pu.customer_id = :customer_id"
        params["customer_id"] = customer_id

    if status:
        status_map = {"active": 1, "finished": 2}
        if status in status_map:
            sql += " AND gs.status = :status"
            params["status"] = status_map[status]

    sql += " ORDER BY gs.start_time DESC LIMIT :limit"

    try:
        results = execute_sql(sql, params)
        if not results:
            return "暂无核销记录"

        status_names = {1: "进行中", 2: "已结束"}
        output = "核销记录:\n"
        for row in results:
            status_name = status_names.get(row["status"], "未知")
            customer = row["customer_name"] or "未知"
            package = row['package_name']
            staff = row["staff_name"] or "未知"
            start_time = row['start_time']
            end_time = row["end_time"] or "进行中"
            output += f"- {customer}: {package} | 核销人: {staff} | {start_time} ~ {end_time} [{status_name}]\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=RefundsQueryInput)
def query_refunds(shop_id: int, purchase_id: Optional[int] = None, status: Optional[str] = None, limit: int = 10) -> str:
    """
    查询退款记录。
    支持按购买记录ID和状态筛选，返回退款金额、状态和时间。
    """
    sql = """
        SELECT
            rr.id,
            rr.purchase_id,
            c.nickname as customer_name,
            p.name as package_name,
            rr.refund_amount,
            rr.deducted_amount,
            rr.reason,
            rr.status,
            rr.created_at
        FROM refund_records rr
        JOIN purchases pu ON rr.purchase_id = pu.id
        JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        WHERE pu.shop_id = :shop_id
    """

    params = {"shop_id": shop_id, "limit": limit}

    if purchase_id:
        sql += " AND rr.purchase_id = :purchase_id"
        params["purchase_id"] = purchase_id

    if status:
        status_map = {"pending": 0, "approved": 1, "rejected": 2}
        if status in status_map:
            sql += " AND rr.status = :status"
            params["status"] = status_map[status]

    sql += " ORDER BY rr.created_at DESC LIMIT :limit"

    try:
        results = execute_sql(sql, params)
        if not results:
            return "暂无退款记录"

        status_names = {0: "处理中", 1: "已批准", 2: "已拒绝"}
        output = "退款记录:\n"
        for row in results:
            status_name = status_names.get(row["status"], "未知")
            customer = row["customer_name"] or "未知"
            package = row['package_name']
            refund_amount = row['refund_amount']
            deducted_amount = row['deducted_amount']
            time = row['created_at']
            output += f"- {customer}: {package} 退款 ¥{refund_amount:.2f}（扣除 ¥{deducted_amount:.2f}）[{status_name}] - {time}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=RefundApproveInput)
def refund_approve(shop_id: int, refund_id: int, remark: Optional[str] = None) -> dict:
    """
    审批退款（批准）。
    批准退款申请，将退款状态改为已批准。
    
    返回确认框数据，需要用户确认后执行。
    """
    # 查询退款信息
    refund_sql = """
        SELECT
            rr.id,
            rr.purchase_id,
            c.nickname as customer_name,
            p.name as package_name,
            rr.refund_amount,
            rr.deducted_amount,
            rr.reason,
            rr.status
        FROM refund_records rr
        JOIN purchases pu ON rr.purchase_id = pu.id
        JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        WHERE rr.id = :refund_id AND pu.shop_id = :shop_id
    """
    refund = execute_sql(refund_sql, {"refund_id": refund_id, "shop_id": shop_id})
    
    if not refund:
        return {"type": "error", "message": "退款记录不存在"}
    
    refund_info = refund[0]
    
    if refund_info["status"] != 0:
        status_names = {1: "已批准", 2: "已拒绝"}
        return {"type": "error", "message": f"该退款已{status_names.get(refund_info['status'], '处理')}"}
    
    # 返回确认框数据
    return {
        "type": "confirm",
        "title": "确认批准退款",
        "message": f"确定要批准 {refund_info['customer_name']} 的退款申请吗？",
        "details": {
            "顾客": refund_info["customer_name"],
            "套餐": refund_info["package_name"],
            "退款金额": f"¥{refund_info['refund_amount']:.2f}",
            "扣除金额": f"¥{refund_info['deducted_amount']:.2f}",
            "退款原因": refund_info["reason"] or "无",
            "备注": remark or "无"
        },
        "action": "refund_approve",
        "params": {
            "shop_id": shop_id,
            "refund_id": refund_id,
            "remark": remark
        }
    }


@tool(args_schema=RefundRejectInput)
def refund_reject(shop_id: int, refund_id: int, reason: str) -> dict:
    """
    审批退款（拒绝）。
    拒绝退款申请，将退款状态改为已拒绝。
    
    返回确认框数据，需要用户确认后执行。
    """
    # 查询退款信息
    refund_sql = """
        SELECT
            rr.id,
            rr.purchase_id,
            c.nickname as customer_name,
            p.name as package_name,
            rr.refund_amount,
            rr.reason,
            rr.status
        FROM refund_records rr
        JOIN purchases pu ON rr.purchase_id = pu.id
        JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        WHERE rr.id = :refund_id AND pu.shop_id = :shop_id
    """
    refund = execute_sql(refund_sql, {"refund_id": refund_id, "shop_id": shop_id})
    
    if not refund:
        return {"type": "error", "message": "退款记录不存在"}
    
    refund_info = refund[0]
    
    if refund_info["status"] != 0:
        status_names = {1: "已批准", 2: "已拒绝"}
        return {"type": "error", "message": f"该退款已{status_names.get(refund_info['status'], '处理')}"}
    
    # 返回确认框数据
    return {
        "type": "confirm",
        "title": "确认拒绝退款",
        "message": f"确定要拒绝 {refund_info['customer_name']} 的退款申请吗？",
        "details": {
            "顾客": refund_info["customer_name"],
            "套餐": refund_info["package_name"],
            "退款金额": f"¥{refund_info['refund_amount']:.2f}",
            "原退款原因": refund_info["reason"] or "无",
            "拒绝原因": reason
        },
        "action": "refund_reject",
        "params": {
            "shop_id": shop_id,
            "refund_id": refund_id,
            "reason": reason
        }
    }


@tool(args_schema=GameSessionCheckinInput)
def game_session_checkin(shop_id: int, customer_id: int, customer_session_id: int) -> dict:
    """
    核销操作（入座）。
    为顾客核销套餐，开始游玩。
    
    返回确认框数据，需要用户确认后执行。
    """
    # 查询顾客信息
    customer_sql = """
        SELECT id, nickname, phone FROM customers WHERE id = :customer_id AND shop_id = :shop_id
    """
    customer = execute_sql(customer_sql, {"customer_id": customer_id, "shop_id": shop_id})
    
    if not customer:
        return {"type": "error", "message": "顾客不存在"}
    
    customer_info = customer[0]
    
    # 查询场次信息
    session_sql = """
        SELECT
            cs.id,
            cs.session_date,
            cs.status,
            p.name as package_name,
            p.duration_minutes
        FROM customer_sessions cs
        JOIN purchases pu ON cs.purchase_id = pu.id
        JOIN packages p ON pu.package_id = p.id
        WHERE cs.id = :customer_session_id AND pu.customer_id = :customer_id AND pu.shop_id = :shop_id
    """
    session = execute_sql(session_sql, {
        "customer_session_id": customer_session_id,
        "customer_id": customer_id,
        "shop_id": shop_id
    })
    
    if not session:
        return {"type": "error", "message": "场次不存在"}
    
    session_info = session[0]
    
    if session_info["status"] != 1:
        status_names = {2: "已核销", 3: "已过期", 4: "已退款"}
        return {"type": "error", "message": f"该场次{status_names.get(session_info['status'], '不可用')}"}
    
    # 返回确认框数据
    return {
        "type": "confirm",
        "title": "确认核销",
        "message": f"确定要为 {customer_info['nickname']} 核销套餐吗？",
        "details": {
            "顾客": customer_info["nickname"],
            "手机": customer_info["phone"] or "未绑定",
            "套餐": session_info["package_name"],
            "时长": f"{session_info['duration_minutes']}分钟",
            "场次日期": str(session_info["session_date"])
        },
        "action": "game_session_checkin",
        "params": {
            "shop_id": shop_id,
            "customer_id": customer_id,
            "customer_session_id": customer_session_id
        }
    }


@tool(args_schema=GameSessionFinishInput)
def game_session_finish(shop_id: int, game_session_id: int) -> dict:
    """
    结束游玩。
    结束顾客的游玩会话，记录结束时间。
    
    返回确认框数据，需要用户确认后执行。
    """
    # 查询游戏场次信息
    session_sql = """
        SELECT
            gs.id,
            c.nickname as customer_name,
            p.name as package_name,
            gs.start_time,
            gs.status
        FROM game_sessions gs
        LEFT JOIN customer_sessions cs ON gs.customer_session_id = cs.id
        LEFT JOIN purchases pu ON cs.purchase_id = pu.id
        LEFT JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        WHERE gs.id = :game_session_id AND gs.shop_id = :shop_id
    """
    session = execute_sql(session_sql, {"game_session_id": game_session_id, "shop_id": shop_id})
    
    if not session:
        return {"type": "error", "message": "游戏场次不存在"}
    
    session_info = session[0]
    
    if session_info["status"] != 1:
        return {"type": "error", "message": "该场次已结束"}
    
    # 返回确认框数据
    return {
        "type": "confirm",
        "title": "确认结束游玩",
        "message": f"确定要结束 {session_info['customer_name']} 的游玩吗？",
        "details": {
            "顾客": session_info["customer_name"],
            "套餐": session_info["package_name"],
            "开始时间": str(session_info["start_time"])
        },
        "action": "game_session_finish",
        "params": {
            "shop_id": shop_id,
            "game_session_id": game_session_id
        }
    }


def execute_refund_approve(shop_id: int, refund_id: int, remark: Optional[str] = None, operator_id: Optional[int] = None) -> str:
    """
    执行退款批准操作（确认后调用）
    """
    try:
        # 更新退款状态
        update_sql = """
            UPDATE refund_records 
            SET status = 1, updated_at = NOW()
            WHERE id = :refund_id
        """
        execute_sql(update_sql, {"refund_id": refund_id})
        
        # 记录操作日志
        if operator_id:
            log_sql = """
                INSERT INTO operation_logs
                (shop_id, operator_id, action, target_type, target_id, detail, created_at)
                VALUES (:shop_id, :operator_id, 'refund_approve', 'refund', :refund_id, :detail, NOW())
            """
            import json
            detail = json.dumps({
                "remark": remark
            }, ensure_ascii=False)
            execute_sql(log_sql, {
                "shop_id": shop_id,
                "operator_id": operator_id,
                "refund_id": refund_id,
                "detail": detail
            })
        
        return "退款审批通过"
    except Exception as e:
        return f"审批失败: {str(e)}"


def execute_refund_reject(shop_id: int, refund_id: int, reason: str, operator_id: Optional[int] = None) -> str:
    """
    执行退款拒绝操作（确认后调用）
    """
    try:
        # 更新退款状态
        update_sql = """
            UPDATE refund_records 
            SET status = 2, reason = :reason, updated_at = NOW()
            WHERE id = :refund_id
        """
        execute_sql(update_sql, {"refund_id": refund_id, "reason": reason})
        
        # 记录操作日志
        if operator_id:
            log_sql = """
                INSERT INTO operation_logs
                (shop_id, operator_id, action, target_type, target_id, detail, created_at)
                VALUES (:shop_id, :operator_id, 'refund_reject', 'refund', :refund_id, :detail, NOW())
            """
            import json
            detail = json.dumps({
                "reason": reason
            }, ensure_ascii=False)
            execute_sql(log_sql, {
                "shop_id": shop_id,
                "operator_id": operator_id,
                "refund_id": refund_id,
                "detail": detail
            })
        
        return "退款已拒绝"
    except Exception as e:
        return f"拒绝失败: {str(e)}"


def execute_game_session_checkin(shop_id: int, customer_id: int, customer_session_id: int, operator_id: Optional[int] = None) -> str:
    """
    执行核销操作（确认后调用）
    """
    try:
        # 更新场次状态
        update_session_sql = """
            UPDATE customer_sessions 
            SET status = 2, updated_at = NOW()
            WHERE id = :customer_session_id
        """
        execute_sql(update_session_sql, {"customer_session_id": customer_session_id})
        
        # 创建游戏场次
        insert_sql = """
            INSERT INTO game_sessions
            (shop_id, customer_session_id, staff_id, start_time, status, created_at)
            VALUES (:shop_id, :customer_session_id, :staff_id, NOW(), 1, NOW())
        """
        execute_sql(insert_sql, {
            "shop_id": shop_id,
            "customer_session_id": customer_session_id,
            "staff_id": operator_id or 0
        })
        
        # 记录操作日志
        if operator_id:
            log_sql = """
                INSERT INTO operation_logs
                (shop_id, operator_id, action, target_type, target_id, detail, created_at)
                VALUES (:shop_id, :operator_id, 'checkin', 'customer_session', :customer_session_id, :detail, NOW())
            """
            import json
            detail = json.dumps({
                "customer_id": customer_id
            }, ensure_ascii=False)
            execute_sql(log_sql, {
                "shop_id": shop_id,
                "operator_id": operator_id,
                "customer_session_id": customer_session_id,
                "detail": detail
            })
        
        return "核销成功"
    except Exception as e:
        return f"核销失败: {str(e)}"


def execute_game_session_finish(shop_id: int, game_session_id: int, operator_id: Optional[int] = None) -> str:
    """
    执行结束游玩操作（确认后调用）
    """
    try:
        # 更新游戏场次状态
        update_sql = """
            UPDATE game_sessions 
            SET status = 2, end_time = NOW(), updated_at = NOW()
            WHERE id = :game_session_id
        """
        execute_sql(update_sql, {"game_session_id": game_session_id})
        
        # 记录操作日志
        if operator_id:
            log_sql = """
                INSERT INTO operation_logs
                (shop_id, operator_id, action, target_type, target_id, detail, created_at)
                VALUES (:shop_id, :operator_id, 'finish', 'game_session', :game_session_id, :detail, NOW())
            """
            import json
            detail = json.dumps({}, ensure_ascii=False)
            execute_sql(log_sql, {
                "shop_id": shop_id,
                "operator_id": operator_id,
                "game_session_id": game_session_id,
                "detail": detail
            })
        
        return "游玩结束"
    except Exception as e:
        return f"操作失败: {str(e)}"
