"""
交易查询和操作工具
使用 Pydantic V2 Schema 约束入参，LangChain StructuredTool 注册

状态映射（来自数据库 sys_dicts）：
- refund_status: 1=处理中(PENDING), 2=已完成(COMPLETED), 3=已拒绝(REJECTED)
- order_status: 1=有效(VALID), 2=已退款(REFUNDED), 3=已过期(EXPIRED)
- game_sessions.status: 1=进行中, 2=已完成
- customer_sessions.status: 1=可用, 2=已核销, 3=已过期, 4=已退款
"""

import json
from pydantic import BaseModel, Field
from typing import Optional
from langchain_core.tools import tool
from app.nl2sql.executor import execute_sql, get_engine


# ==================== Input Schemas ====================

class PurchasesQueryInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    customer_id: Optional[int] = Field(default=None, description="顾客ID（可选）")
    status: Optional[str] = Field(default=None, description="状态: valid=有效, refunded=已退款, expired=已过期")
    limit: int = Field(default=10, description="返回数量")

class GameSessionsQueryInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    customer_id: Optional[int] = Field(default=None, description="顾客ID（可选）")
    status: Optional[str] = Field(default=None, description="状态: active=进行中, finished=已结束")
    limit: int = Field(default=10, description="返回数量")

class RefundsQueryInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    purchase_id: Optional[int] = Field(default=None, description="购买记录ID（可选）")
    status: Optional[str] = Field(default=None, description="状态: pending=处理中, completed=已完成, rejected=已拒绝")
    limit: int = Field(default=10, description="返回数量")

class RefundApproveInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    refund_id: int = Field(description="退款记录ID")
    remark: Optional[str] = Field(default=None, description="审批备注")

class RefundRejectInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    refund_id: int = Field(description="退款记录ID")
    reason: Optional[str] = Field(default=None, description="拒绝原因（用户在确认框中填写）")

class GameSessionCheckinInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    customer_id: int = Field(description="顾客ID")
    customer_session_id: int = Field(description="顾客场次ID")

class GameSessionFinishInput(BaseModel):
    shop_id: int = Field(description="店铺ID")
    game_session_id: int = Field(description="游戏场次ID")


# ==================== 查询工具 ====================

@tool(args_schema=PurchasesQueryInput)
def query_purchases(shop_id: int, customer_id: Optional[int] = None, status: Optional[str] = None, limit: int = 10) -> str:
    """查询购买记录。支持按顾客ID和状态筛选。"""
    sql = """
        SELECT pu.id, pu.customer_id, c.nickname as customer_name,
               p.name as package_name, pu.total_amount, pu.paid_amount,
               pu.status, pu.created_at
        FROM purchases pu
        JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        WHERE pu.shop_id = :shop_id AND pu.is_deleted = 0
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
            sn = status_names.get(row["status"], "未知")
            c = row["customer_name"] or "未知顾客"
            output += f"- {c}: {row['package_name']} ¥{row['paid_amount']:.2f}（{sn}）- {row['created_at']}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=GameSessionsQueryInput)
def query_game_sessions(shop_id: int, customer_id: Optional[int] = None, status: Optional[str] = None, limit: int = 10) -> str:
    """查询核销/游玩记录。支持按顾客ID和状态筛选。"""
    sql = """
        SELECT gs.id, gs.customer_session_id, c.nickname as customer_name,
               p.name as package_name, s.name as staff_name,
               gs.start_time, gs.end_time, gs.status
        FROM game_sessions gs
        LEFT JOIN customer_sessions cs ON gs.customer_session_id = cs.id
        LEFT JOIN purchases pu ON cs.purchase_id = pu.id
        LEFT JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        LEFT JOIN staff s ON gs.staff_id = s.id
        WHERE gs.shop_id = :shop_id AND (gs.is_deleted = 0 OR gs.is_deleted IS NULL)
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
            sn = status_names.get(row["status"], "未知")
            c = row["customer_name"] or "未知"
            s = row["staff_name"] or "未知"
            end = row["end_time"] or "进行中"
            output += f"- {c}: {row['package_name']} | 核销人: {s} | {row['start_time']} ~ {end} [{sn}]\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool(args_schema=RefundsQueryInput)
def query_refunds(shop_id: int, purchase_id: Optional[int] = None, status: Optional[str] = None, limit: int = 10) -> str:
    """查询退款记录。支持按购买记录ID和状态筛选。"""
    sql = """
        SELECT rr.id, rr.purchase_id, c.nickname as customer_name,
               p.name as package_name, rr.refund_amount, rr.deducted_amount,
               rr.reason, rr.status, rr.created_at
        FROM refund_records rr
        JOIN purchases pu ON rr.purchase_id = pu.id
        JOIN packages p ON pu.package_id = p.id
        LEFT JOIN customers c ON pu.customer_id = c.id
        WHERE pu.shop_id = :shop_id AND rr.is_deleted = 0
    """
    params = {"shop_id": shop_id, "limit": limit}
    if purchase_id:
        sql += " AND rr.purchase_id = :purchase_id"
        params["purchase_id"] = purchase_id
    if status:
        status_map = {"pending": 1, "completed": 2, "rejected": 3}
        if status in status_map:
            sql += " AND rr.status = :status"
            params["status"] = status_map[status]
    sql += " ORDER BY rr.created_at DESC LIMIT :limit"
    try:
        results = execute_sql(sql, params)
        if not results:
            return "暂无退款记录"
        status_names = {1: "处理中", 2: "已完成", 3: "已拒绝"}
        output = "退款记录:\n"
        for row in results:
            sn = status_names.get(row["status"], "未知")
            c = row["customer_name"] or "未知"
            output += f"- [{row['id']}] {c}: {row['package_name']} 退款 ¥{row['refund_amount']:.2f}（扣除 ¥{row['deducted_amount']:.2f}）[{sn}] - {row['created_at']}\n"
        return output
    except Exception as e:
        return f"查询失败: {str(e)}"


# ==================== 确认框工具（返回确认数据，不执行写操作）====================

@tool(args_schema=RefundApproveInput)
def refund_approve(shop_id: int, refund_id: int, remark: Optional[str] = None) -> dict:
    """审批退款（批准）。返回确认框，需用户确认后执行。"""
    try:
        # ===== 参数完整性检查：refund_id =====
        if not refund_id or refund_id == 0:
            pending = execute_sql(
                "SELECT rr.id, c.nickname, p.name as package_name, rr.refund_amount, rr.reason "
                "FROM refund_records rr "
                "JOIN purchases pu ON rr.purchase_id = pu.id "
                "JOIN packages p ON pu.package_id = p.id "
                "LEFT JOIN customers c ON pu.customer_id = c.id "
                "WHERE pu.shop_id = :sid AND rr.status = 1 AND rr.is_deleted = 0 "
                "ORDER BY rr.created_at DESC",
                {"sid": shop_id}
            )
            if not pending:
                return {"type": "error", "message": "当前没有待处理的退款申请"}
            return {
                "type": "confirm",
                "tool_name": "refund_approve",
                "title": "批准退款",
                "message": "请选择要批准的退款记录：",
                "details": {},
                "fields": [
                    {
                        "name": "refund_id",
                        "type": "select",
                        "label": "退款记录",
                        "required": True,
                        "options": [
                            {"value": r["id"], "label": f"{r['nickname']} - {r['package_name']} ¥{r['refund_amount']:.2f} ({r['reason'] or '无原因'})"}
                            for r in pending
                        ],
                    },
                    {"name": "remark", "type": "input", "label": "审批备注", "required": False, "placeholder": "可选填写备注", "value": remark or ""},
                ],
                "buttons": [
                    {"type": "confirm", "label": "确认批准"},
                    {"type": "cancel", "label": "取消"},
                ],
                "action": "refund_approve",
                "params": {"shop_id": shop_id},
            }

        # ===== 参数齐全 =====
        refund_sql = """
            SELECT rr.id, rr.purchase_id, c.nickname as customer_name,
                   p.name as package_name, rr.refund_amount, rr.deducted_amount,
                   rr.reason, rr.status
            FROM refund_records rr
            JOIN purchases pu ON rr.purchase_id = pu.id
            JOIN packages p ON pu.package_id = p.id
            LEFT JOIN customers c ON pu.customer_id = c.id
            WHERE rr.id = :refund_id AND pu.shop_id = :shop_id AND rr.is_deleted = 0
        """
        refund = execute_sql(refund_sql, {"refund_id": refund_id, "shop_id": shop_id})
        if not refund:
            return {"type": "error", "message": "退款记录不存在"}
        info = refund[0]
        if info["status"] != 1:
            status_names = {2: "已完成", 3: "已拒绝"}
            return {"type": "error", "message": f"该退款已{status_names.get(info['status'], '处理完毕')}"}
        return {
            "type": "confirm",
            "tool_name": "refund_approve",
            "title": "确认批准退款",
            "message": f"确定要批准 {info['customer_name']} 的退款申请吗？",
            "details": {
                "顾客": info["customer_name"],
                "套餐": info["package_name"],
                "退款金额": f"¥{info['refund_amount']:.2f}",
                "扣除金额": f"¥{info['deducted_amount']:.2f}",
                "退款原因": info["reason"] or "无",
            },
            "fields": [
                {"name": "remark", "type": "input", "label": "审批备注", "required": False, "placeholder": "可选填写备注", "value": remark or ""}
            ],
            "buttons": [
                {"type": "confirm", "label": "确认批准"},
                {"type": "cancel", "label": "取消"}
            ],
            "action": "refund_approve",
            "params": {"shop_id": shop_id, "refund_id": refund_id}
        }
    except Exception as e:
        return {"type": "error", "message": f"查询失败: {str(e)}"}


@tool(args_schema=RefundRejectInput)
def refund_reject(shop_id: int, refund_id: int, reason: Optional[str] = None) -> dict:
    """审批退款（拒绝）。返回确认框，需用户确认后执行。"""
    try:
        # ===== 参数完整性检查：refund_id =====
        if not refund_id or refund_id == 0:
            # 查询待处理退款列表
            pending = execute_sql(
                "SELECT rr.id, c.nickname, p.name as package_name, rr.refund_amount, rr.reason "
                "FROM refund_records rr "
                "JOIN purchases pu ON rr.purchase_id = pu.id "
                "JOIN packages p ON pu.package_id = p.id "
                "LEFT JOIN customers c ON pu.customer_id = c.id "
                "WHERE pu.shop_id = :sid AND rr.status = 1 AND rr.is_deleted = 0 "
                "ORDER BY rr.created_at DESC",
                {"sid": shop_id}
            )
            if not pending:
                return {"type": "error", "message": "当前没有待处理的退款申请"}
            return {
                "type": "confirm",
                "tool_name": "refund_reject",
                "title": "拒绝退款",
                "message": "请选择要拒绝的退款记录：",
                "details": {},
                "fields": [
                    {
                        "name": "refund_id",
                        "type": "select",
                        "label": "退款记录",
                        "required": True,
                        "options": [
                            {"value": r["id"], "label": f"{r['nickname']} - {r['package_name']} ¥{r['refund_amount']:.2f} ({r['reason'] or '无原因'})"}
                            for r in pending
                        ],
                    },
                    {"name": "reason", "type": "input", "label": "拒绝理由", "required": True, "placeholder": "请输入拒绝原因", "value": reason or ""},
                ],
                "buttons": [
                    {"type": "confirm", "label": "确认拒绝"},
                    {"type": "cancel", "label": "取消"},
                ],
                "action": "refund_reject",
                "params": {"shop_id": shop_id},
            }

        # ===== 参数齐全，查询退款详情 =====
        refund_sql = """
            SELECT rr.id, rr.purchase_id, c.nickname as customer_name,
                   p.name as package_name, rr.refund_amount, rr.reason, rr.status
            FROM refund_records rr
            JOIN purchases pu ON rr.purchase_id = pu.id
            JOIN packages p ON pu.package_id = p.id
            LEFT JOIN customers c ON pu.customer_id = c.id
            WHERE rr.id = :refund_id AND pu.shop_id = :shop_id AND rr.is_deleted = 0
        """
        refund = execute_sql(refund_sql, {"refund_id": refund_id, "shop_id": shop_id})
        if not refund:
            return {"type": "error", "message": "退款记录不存在"}
        info = refund[0]
        if info["status"] != 1:
            status_names = {2: "已完成", 3: "已拒绝"}
            return {"type": "error", "message": f"该退款已{status_names.get(info['status'], '处理完毕')}"}
        return {
            "type": "confirm",
            "tool_name": "refund_reject",
            "title": "确认拒绝退款",
            "message": f"确定要拒绝 {info['customer_name']} 的退款申请吗？",
            "details": {
                "顾客": info["customer_name"],
                "套餐": info["package_name"],
                "退款金额": f"¥{info['refund_amount']:.2f}",
                "原退款原因": info["reason"] or "无",
            },
            "fields": [
                {"name": "reason", "type": "input", "label": "拒绝理由", "required": True, "placeholder": "请输入拒绝原因", "value": reason or ""}
            ],
            "buttons": [
                {"type": "confirm", "label": "确认拒绝"},
                {"type": "cancel", "label": "取消"}
            ],
            "action": "refund_reject",
            "params": {"shop_id": shop_id, "refund_id": refund_id}
        }
    except Exception as e:
        return {"type": "error", "message": f"查询失败: {str(e)}"}


@tool(args_schema=GameSessionCheckinInput)
def game_session_checkin(shop_id: int, customer_id: int, customer_session_id: int) -> dict:
    """核销入座。返回确认框，需用户确认后执行。"""
    try:
        fields = []

        # ===== 检查 customer_id =====
        if not customer_id or customer_id == 0:
            # 查询有可用场次的顾客
            customers = execute_sql(
                "SELECT DISTINCT c.id, c.nickname, c.phone "
                "FROM customers c "
                "JOIN customer_sessions cs ON c.id = cs.customer_id "
                "WHERE cs.shop_id = :sid AND cs.status = 1 AND cs.is_deleted = 0 AND c.is_deleted = 0 "
                "ORDER BY c.nickname",
                {"sid": shop_id}
            )
            if not customers:
                return {"type": "error", "message": "当前没有待核销的顾客"}
            fields.append({
                "name": "customer_id",
                "type": "select",
                "label": "选择顾客",
                "required": True,
                "options": [
                    {"value": str(c["id"]), "label": f"{c['nickname']} ({c['phone'] or '无手机'})"}
                    for c in customers
                ],
            })

        # ===== 检查 customer_session_id =====
        if not customer_session_id or customer_session_id == 0:
            # 如果已选顾客，查询该顾客的可用场次
            if customer_id and customer_id != 0:
                sessions = execute_sql(
                    "SELECT cs.id, p.name as package_name, cs.session_date "
                    "FROM customer_sessions cs "
                    "JOIN purchases pu ON cs.purchase_id = pu.id "
                    "JOIN packages p ON pu.package_id = p.id "
                    "WHERE cs.customer_id = :cid AND cs.shop_id = :sid AND cs.status = 1 AND cs.is_deleted = 0 "
                    "ORDER BY cs.session_date DESC",
                    {"cid": customer_id, "sid": shop_id}
                )
            else:
                # 未选顾客，查询所有可用场次
                sessions = execute_sql(
                    "SELECT cs.id, c.nickname, p.name as package_name, cs.session_date "
                    "FROM customer_sessions cs "
                    "JOIN purchases pu ON cs.purchase_id = pu.id "
                    "JOIN packages p ON pu.package_id = p.id "
                    "LEFT JOIN customers c ON cs.customer_id = c.id "
                    "WHERE cs.shop_id = :sid AND cs.status = 1 AND cs.is_deleted = 0 "
                    "ORDER BY cs.session_date DESC",
                    {"sid": shop_id}
                )
            if not sessions:
                return {"type": "error", "message": "当前没有可用的场次"}
            fields.append({
                "name": "customer_session_id",
                "type": "select",
                "label": "选择场次",
                "required": True,
                "options": [
                    {"value": str(s["id"]), "label": f"{s.get('nickname', '')} - {s['package_name']} ({s['session_date']})"}
                    for s in sessions
                ],
            })

        # ===== 有缺失字段 → 返回填写表单 =====
        if fields:
            return {
                "type": "confirm",
                "tool_name": "game_session_checkin",
                "title": "核销入座",
                "message": "请选择要核销的场次：",
                "details": {},
                "fields": fields,
                "buttons": [
                    {"type": "confirm", "label": "确认核销"},
                    {"type": "cancel", "label": "取消"},
                ],
                "action": "game_session_checkin",
                "params": {"shop_id": shop_id, **({"customer_id": customer_id} if customer_id else {}), **({"customer_session_id": customer_session_id} if customer_session_id else {})},
            }

        # ===== 参数齐全，查询场次详情 =====
        session_sql = """
            SELECT cs.id, cs.status, p.name as package_name, p.duration_minutes,
                   cs.session_date, c.nickname, c.phone
            FROM customer_sessions cs
            JOIN purchases pu ON cs.purchase_id = pu.id
            JOIN packages p ON pu.package_id = p.id
            LEFT JOIN customers c ON cs.customer_id = c.id
            WHERE cs.id = :customer_session_id AND cs.shop_id = :shop_id AND cs.is_deleted = 0
        """
        session = execute_sql(session_sql, {"customer_session_id": customer_session_id, "shop_id": shop_id})
        if not session:
            return {"type": "error", "message": "场次不存在"}
        info = session[0]
        if info["status"] != 1:
            status_names = {2: "已核销", 3: "已过期", 4: "已退款"}
            return {"type": "error", "message": f"该场次{status_names.get(info['status'], '不可用')}"}
        return {
            "type": "confirm",
            "tool_name": "game_session_checkin",
            "title": "确认核销",
            "message": f"确定要为 {info['nickname']} 核销套餐吗？",
            "details": {
                "顾客": info["nickname"], "手机": info["phone"] or "未绑定",
                "套餐": info["package_name"], "时长": f"{info['duration_minutes']}分钟",
                "场次日期": str(info["session_date"])
            },
            "fields": [],
            "buttons": [
                {"type": "confirm", "label": "确认核销"},
                {"type": "cancel", "label": "取消"}
            ],
            "action": "game_session_checkin",
            "params": {"shop_id": shop_id, "customer_id": customer_id, "customer_session_id": customer_session_id}
        }
    except Exception as e:
        return {"type": "error", "message": f"查询失败: {str(e)}"}


@tool(args_schema=GameSessionFinishInput)
def game_session_finish(shop_id: int, game_session_id: int) -> dict:
    """结束游玩。返回确认框，需用户确认后执行。"""
    try:
        # ===== 参数完整性检查 =====
        if not game_session_id or game_session_id == 0:
            # 查询进行中的场次
            sessions = execute_sql(
                "SELECT gs.id, c.nickname, p.name as package_name, gs.start_time "
                "FROM game_sessions gs "
                "LEFT JOIN customer_sessions cs ON gs.customer_session_id = cs.id "
                "LEFT JOIN purchases pu ON cs.purchase_id = pu.id "
                "LEFT JOIN packages p ON pu.package_id = p.id "
                "LEFT JOIN customers c ON pu.customer_id = c.id "
                "WHERE gs.shop_id = :sid AND gs.status = 1 AND (gs.is_deleted = 0 OR gs.is_deleted IS NULL)",
                {"sid": shop_id}
            )
            if not sessions:
                return {"type": "error", "message": "当前没有进行中的场次"}
            return {
                "type": "confirm",
                "tool_name": "game_session_finish",
                "title": "结束游玩",
                "message": "请选择要结束的场次：",
                "details": {},
                "fields": [
                    {
                        "name": "game_session_id",
                        "type": "select",
                        "label": "选择场次",
                        "required": True,
                        "options": [
                            {"value": str(s["id"]), "label": f"{s['nickname'] or '未知'} - {s['package_name']} ({s['start_time']})"}
                            for s in sessions
                        ],
                    },
                ],
                "buttons": [
                    {"type": "confirm", "label": "确认结束"},
                    {"type": "cancel", "label": "取消"},
                ],
                "action": "game_session_finish",
                "params": {"shop_id": shop_id},
            }

        # ===== 参数齐全 =====
        session_sql = """
            SELECT gs.id, c.nickname as customer_name, p.name as package_name,
                   gs.start_time, gs.status
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
        info = session[0]
        if info["status"] != 1:
            return {"type": "error", "message": "该场次已结束"}
        return {
            "type": "confirm",
            "tool_name": "game_session_finish",
            "title": "确认结束游玩",
            "message": f"确定要结束 {info['customer_name']} 的游玩吗？",
            "details": {
                "顾客": info["customer_name"], "套餐": info["package_name"],
                "开始时间": str(info["start_time"])
            },
            "fields": [],
            "buttons": [
                {"type": "confirm", "label": "确认结束"},
                {"type": "cancel", "label": "取消"}
            ],
            "action": "game_session_finish",
            "params": {"shop_id": shop_id, "game_session_id": game_session_id}
        }
    except Exception as e:
        return {"type": "error", "message": f"查询失败: {str(e)}"}


# ==================== 执行函数（确认后调用，带事务）====================

def execute_refund_approve(shop_id: int, refund_id: int, remark: Optional[str] = None, operator_id: Optional[int] = None, token: Optional[str] = None) -> str:
    """执行退款批准 - 代理调用 Java 后端 API"""
    from app.common.backend_client import approve_refund

    try:
        result = approve_refund(token=token or "", shop_id=shop_id, refund_id=refund_id)
        if result.get("success"):
            return "退款审批通过"
        return result.get("msg", "确认退款失败")
    except Exception as e:
        return f"审批失败: {str(e)}"


def execute_refund_reject(shop_id: int, refund_id: int, reason: Optional[str] = None, operator_id: Optional[int] = None, token: Optional[str] = None) -> str:
    """执行退款拒绝 - 代理调用 Java 后端 API"""
    from app.common.backend_client import reject_refund

    try:
        result = reject_refund(token=token or "", shop_id=shop_id, refund_id=refund_id, reason=reason or "")
        if result.get("success"):
            return "退款已拒绝"
        return result.get("msg", "拒绝退款失败")
    except Exception as e:
        return f"拒绝失败: {str(e)}"


def execute_game_session_checkin(shop_id: int, customer_id: int, customer_session_id: int, operator_id: Optional[int] = None, token: Optional[str] = None) -> str:
    """执行核销入座 - 代理调用 Java 后端 API"""
    from app.common.backend_client import checkin_game_session

    try:
        result = checkin_game_session(
            token=token or "", shop_id=shop_id,
            customer_id=customer_id, customer_session_id=customer_session_id,
        )
        if result.get("success"):
            return "核销成功"
        return result.get("msg", "核销失败")
    except Exception as e:
        return f"核销失败: {str(e)}"


def execute_game_session_finish(shop_id: int, game_session_id: int, operator_id: Optional[int] = None, token: Optional[str] = None) -> str:
    """执行结束游玩 - 代理调用 Java 后端 API"""
    from app.common.backend_client import finish_game_session

    try:
        result = finish_game_session(token=token or "", shop_id=shop_id, game_session_id=game_session_id)
        if result.get("success"):
            return "游玩结束"
        return result.get("msg", "操作失败")
    except Exception as e:
        return f"操作失败: {str(e)}"
