"""
工具参数解析计划

声明每个操作工具需要哪些参数、参数来源、以及关联的查询工具。
执行流程：LLM 提取中间变量(名称/标记) → 查询工具解析名称→ID → 调用工具

设计原则：
1. QUERY_TOOL_FILTERS: 查询工具的完整 SQL 配置（base_from 支持 JOIN，display_field 支持跨表字段）
2. TOOL_PARAM_PLANS: 操作工具的参数解析计划（from_query 声明 extract_field 告诉 LLM 提取什么名称）
3. extract_field: LLM 应该从用户消息中提取的中间变量名（如 coupon_name，不是 coupon_id）
4. derived: 可以从查询结果中推导的参数（如 customer_id 可以从 game_session 推导）
"""

# ==================== 查询工具配置 ====================
# base_from: 完整的 FROM + JOIN 子句
# display_field: SELECT 中用于显示名称的表达式（可能是跨表字段）
# id_field: 主键字段
# extra_fields: 额外 SELECT 的字段（用于 derived 推导）

QUERY_TOOL_FILTERS = {
    "query_coupons": {
        "description": "查询优惠券列表",
        "base_from": "coupons",
        "id_field": "id",
        "display_field": "name",
        "extra_fields": ["type", "value", "remain_stock"],
        "filters": [
            {"param": "name", "field": "name", "match": "LIKE", "description": "优惠券名称"},
            {"param": "status", "field": "is_active", "match": "EQ",
             "values": {"active": 1, "disabled": 0, "已启用": 1, "已禁用": 0, "启用": 1, "禁用": 0},
             "description": "状态"},
        ],
    },
    "query_customer": {
        "description": "查询顾客信息",
        "base_from": "customers",
        "id_field": "id",
        "display_field": "nickname",
        "extra_fields": ["phone"],
        "filters": [
            {"param": "keyword", "field": "nickname", "match": "LIKE", "description": "顾客姓名或手机号"},
            {"param": "phone", "field": "phone", "match": "EQ", "description": "手机号"},
        ],
    },
    "query_refunds": {
        "description": "查询退款记录",
        "base_from": "refund_records rr LEFT JOIN customers c ON rr.customer_id = c.id",
        "id_field": "rr.id",
        "display_field": "CONCAT(c.nickname, ' - ¥', FORMAT(rr.refund_amount, 2))",
        "extra_fields": ["rr.refund_amount", "rr.status", "rr.reason", "rr.customer_id", "rr.purchase_id"],
        "filters": [
            {"param": "status", "field": "rr.status", "match": "EQ",
             "values": {"pending": 1, "completed": 2, "rejected": 3, "待处理": 1, "已退款": 2, "已拒绝": 3},
             "description": "退款状态"},
            {"param": "customer_name", "field": "c.nickname", "match": "LIKE", "description": "顾客姓名"},
        ],
    },
    "query_feedbacks": {
        "description": "查询顾客评价",
        "base_from": "feedbacks f LEFT JOIN customers c ON f.customer_id = c.id",
        "id_field": "f.id",
        "display_field": "CONCAT(c.nickname, ': ', LEFT(f.content, 20))",
        "extra_fields": ["f.content", "f.status", "f.customer_id"],
        "filters": [
            {"param": "status", "field": "f.status", "match": "EQ",
             "values": {"pending": 1, "replied": 2, "待回复": 1, "已回复": 2},
             "description": "状态"},
            {"param": "customer_name", "field": "c.nickname", "match": "LIKE", "description": "顾客姓名"},
        ],
    },
    "query_inventory": {
        "description": "查询库存信息",
        "base_from": "inventory inv LEFT JOIN materials m ON inv.material_id = m.id",
        "id_field": "inv.material_id",
        "display_field": "m.name",
        "extra_fields": ["inv.quantity", "m.unit", "m.min_stock", "m.type"],
        "filters": [
            {"param": "keyword", "field": "m.name", "match": "LIKE", "description": "物料名称"},
            {"param": "category", "field": "m.category", "match": "EQ", "description": "物料分类"},
        ],
    },
    "query_game_sessions": {
        "description": "查询游玩场次",
        "base_from": "game_sessions gs LEFT JOIN customers c ON gs.customer_id = c.id",
        "id_field": "gs.id",
        "display_field": "CONCAT(c.nickname, ' - ', DATE(gs.start_time))",
        "extra_fields": ["gs.customer_id", "gs.customer_session_id", "gs.status", "gs.start_time"],
        "filters": [
            {"param": "status", "field": "gs.status", "match": "EQ",
             "values": {"active": 1, "finished": 2, "进行中": 1, "已结束": 2},
             "description": "状态"},
            {"param": "customer_name", "field": "c.nickname", "match": "LIKE", "description": "顾客姓名"},
        ],
    },
    "query_staff_list": {
        "description": "查询员工列表",
        "base_from": "staff s LEFT JOIN staff_shops ss ON s.id = ss.staff_id",
        "id_field": "s.id",
        "display_field": "s.name",
        "extra_fields": ["s.phone"],
        "filters": [
            {"param": "keyword", "field": "s.name", "match": "LIKE", "description": "员工姓名"},
        ],
    },
}

# ==================== 操作工具参数解析计划 ====================
# extract_field: LLM 应该从用户消息中提取的中间变量名（名称/标记，不是 ID）
# extra_filter: 查询时追加的固定条件
# derived: 从查询结果的额外字段推导参数

TOOL_PARAM_PLANS = {
    "grant_coupon": {
        "required_params": ["coupon_id", "customer_ids"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "coupon_id": {
                "query_tool": "query_coupons",
                "extract_field": "coupon_name",     # LLM 提取: "兑换券（免费石膏涂色）"
                "description": "优惠券ID",
            },
            "customer_ids": {
                "query_tool": "query_customer",
                "extract_field": "customer_filter",  # LLM 提取: "ALL" 或 "张三"
                "description": "顾客ID列表",
                "concat": True,                      # 多个 ID 用逗号连接
            },
        },
        "user_input": [],
        "confirm_template": {
            "title": "确认发放优惠券",
            "message": "确定要发放优惠券给选中的顾客吗？",
        },
    },
    "refund_reject": {
        "required_params": ["refund_id", "reason"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "refund_id": {
                "query_tool": "query_refunds",
                "extract_field": "customer_name",    # LLM 提取: "张三"
                "extra_filter": {"status": "pending"},
                "description": "退款记录ID",
            },
        },
        "user_input": ["reason"],
        "confirm_template": {
            "title": "确认拒绝退款",
            "message": "确定要拒绝这笔退款申请吗？",
        },
    },
    "refund_approve": {
        "required_params": ["refund_id"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "refund_id": {
                "query_tool": "query_refunds",
                "extract_field": "customer_name",
                "extra_filter": {"status": "pending"},
                "description": "退款记录ID",
            },
        },
        "user_input": ["remark"],
        "confirm_template": {
            "title": "确认批准退款",
            "message": "确定要批准这笔退款申请吗？",
        },
    },
    "game_session_checkin": {
        "required_params": ["customer_id", "customer_session_id"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "customer_session_id": {
                "query_tool": "query_game_sessions",
                "extract_field": "customer_name",
                "extra_filter": {"status": "active"},
                "description": "可用场次ID",
            },
            "customer_id": {
                "query_tool": "query_game_sessions",
                "extract_field": "customer_name",
                "extra_filter": {"status": "active"},
                "description": "顾客ID",
                "derived_from": "customer_session_id",  # 从同一个查询结果推导
                "derived_field": "customer_id",          # 取 extra_fields 中的 gs.customer_id
            },
        },
        "user_input": [],
        "confirm_template": {
            "title": "确认核销",
            "message": "确定要核销吗？",
        },
    },
    "game_session_finish": {
        "required_params": ["game_session_id"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "game_session_id": {
                "query_tool": "query_game_sessions",
                "extract_field": "customer_name",
                "extra_filter": {"status": "active"},
                "description": "进行中的场次ID",
            },
        },
        "user_input": [],
        "confirm_template": {
            "title": "确认结束游玩",
            "message": "确定要结束游玩吗？",
        },
    },
    "material_inbound": {
        "required_params": ["material_id", "quantity"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "material_id": {
                "query_tool": "query_inventory",
                "extract_field": "material_name",    # LLM 提取: "石膏娃娃"
                "description": "物料ID",
            },
        },
        "user_input": ["quantity"],
        "confirm_template": {
            "title": "确认入库",
            "message": "确定要入库吗？",
        },
    },
    "material_outbound": {
        "required_params": ["material_id", "quantity"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "material_id": {
                "query_tool": "query_inventory",
                "extract_field": "material_name",
                "description": "物料ID",
            },
        },
        "user_input": ["quantity"],
        "confirm_template": {
            "title": "确认出库",
            "message": "确定要出库吗？",
        },
    },
    "reply_feedback": {
        "required_params": ["feedback_id", "reply_content"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "feedback_id": {
                "query_tool": "query_feedbacks",
                "extract_field": "customer_name",    # LLM 提取: "张三"
                "extra_filter": {"status": "pending"},
                "description": "评价ID",
            },
        },
        "user_input": ["reply_content"],
        "confirm_template": {
            "title": "确认回复评价",
            "message": "确定要回复这条评价吗？",
        },
    },
    "send_notification": {
        "required_params": ["recipient_ids", "title", "content"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "recipient_ids": {
                "query_tool": "query_customer",      # 默认查顾客，运行时根据 recipient_type 覆盖
                "extract_field": "recipient_filter",  # LLM 提取: "ALL" 或 "张三"
                "description": "接收者ID列表",
                "concat": True,
                "dynamic_tool_by": "recipient_type",  # 运行时: customer→query_customer, staff→query_staff_list
            },
        },
        "user_input": ["recipient_type", "title", "content"],
        "confirm_template": {
            "title": "发送通知",
            "message": "请填写通知内容：",
        },
    },
}
