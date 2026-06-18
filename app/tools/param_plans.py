"""
工具参数解析计划

声明每个操作工具需要哪些参数、参数来源、以及关联的查询工具。
LLM 根据此信息编排参数解析步骤。

设计原则：
1. 操作工具声明需要哪些参数
2. 参数分为三类：pre_filled(系统填入)、from_query(查询工具获取)、user_input(用户填写)
3. 查询工具声明支持的搜索条件
4. LLM 根据用户意图和工具需求，编排查询步骤
"""

# ==================== 查询工具搜索条件定义 ====================
# 从 Pydantic schema 的 description 自动推导，不重复定义

QUERY_TOOL_FILTERS = {
    "query_coupons": {
        "description": "查询优惠券列表",
        "table": "coupons",
        "id_field": "id",
        "name_field": "name",
        "filters": [
            {"param": "name", "field": "name", "match": "LIKE", "description": "优惠券名称"},
            {"param": "status", "field": "is_active", "match": "EQ", "values": {"active": 1, "disabled": 0}, "description": "状态"},
        ],
    },
    "query_customer": {
        "description": "查询顾客信息",
        "table": "customers",
        "id_field": "id",
        "name_field": "nickname",
        "filters": [
            {"param": "keyword", "field": "nickname", "match": "LIKE", "description": "顾客姓名或手机号"},
        ],
    },
    "query_refunds": {
        "description": "查询退款记录",
        "table": "refund_records",
        "id_field": "id",
        "name_field": "reason",
        "filters": [
            {"param": "status", "field": "status", "match": "EQ", "values": {"pending": 1, "completed": 2, "rejected": 3}, "description": "退款状态"},
            {"param": "customer_name", "field": "nickname", "match": "LIKE", "description": "顾客姓名", "join": "customers ON refund_records.customer_id = customers.id"},
        ],
    },
    "query_feedbacks": {
        "description": "查询顾客评价",
        "table": "feedbacks",
        "id_field": "id",
        "name_field": "content",
        "filters": [
            {"param": "status", "field": "status", "match": "EQ", "values": {"pending": 1, "replied": 2}, "description": "状态"},
        ],
    },
    "query_inventory": {
        "description": "查询库存信息",
        "table": "inventory",
        "id_field": "material_id",
        "name_field": "name",
        "filters": [
            {"param": "keyword", "field": "name", "match": "LIKE", "description": "物料名称", "join": "materials ON inventory.material_id = materials.id"},
        ],
    },
    "query_game_sessions": {
        "description": "查询游玩场次",
        "table": "game_sessions",
        "id_field": "id",
        "name_field": "nickname",
        "filters": [
            {"param": "status", "field": "status", "match": "EQ", "values": {"active": 1, "finished": 2}, "description": "状态"},
            {"param": "customer_name", "field": "nickname", "match": "LIKE", "description": "顾客姓名", "join": "customers ON game_sessions.customer_id = customers.id"},
        ],
    },
}

# ==================== 操作工具参数解析计划 ====================

TOOL_PARAM_PLANS = {
    "grant_coupon": {
        "required_params": ["coupon_id", "customer_ids"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "coupon_id": {
                "query_tool": "query_coupons",
                "extract_by": "name",       # 从用户消息中提取优惠券名称，按 name 查询
                "description": "优惠券ID",
            },
            "customer_ids": {
                "query_tool": "query_customer",
                "extract_by": "all_or_name",  # "所有"/"全部" → 查全部；否则按名称查
                "description": "顾客ID列表",
                "concat": True,              # 多个 ID 用逗号连接
            },
        },
        "user_input": [],
        "confirm_template": {
            "title": "确认发放优惠券",
            "message": "确定要发放优惠券给选中的顾客吗？",
            "details": ["优惠券名称", "发放人数", "库存"],
        },
    },
    "refund_reject": {
        "required_params": ["refund_id", "reason"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "refund_id": {
                "query_tool": "query_refunds",
                "extract_by": "customer_name",  # 从用户消息提取顾客名，按顾客查退款
                "extra_filter": {"status": "pending"},  # 只查待处理的
                "description": "退款记录ID",
            },
        },
        "user_input": ["reason"],
        "confirm_template": {
            "title": "确认拒绝退款",
            "message": "确定要拒绝这笔退款申请吗？",
            "details": ["顾客", "套餐", "退款金额"],
        },
    },
    "refund_approve": {
        "required_params": ["refund_id"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "refund_id": {
                "query_tool": "query_refunds",
                "extract_by": "customer_name",
                "extra_filter": {"status": "pending"},
                "description": "退款记录ID",
            },
        },
        "user_input": ["remark"],
        "confirm_template": {
            "title": "确认批准退款",
            "message": "确定要批准这笔退款申请吗？",
            "details": ["顾客", "套餐", "退款金额"],
        },
    },
    "game_session_checkin": {
        "required_params": ["customer_id", "customer_session_id"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "customer_id": {
                "query_tool": "query_customer",
                "extract_by": "name",
                "description": "顾客ID",
            },
            "customer_session_id": {
                "query_tool": "query_game_sessions",
                "extract_by": "customer_name",
                "extra_filter": {"status": "active"},
                "description": "可用场次ID",
            },
        },
        "user_input": [],
        "confirm_template": {
            "title": "确认核销",
            "message": "确定要核销吗？",
            "details": ["顾客", "套餐", "场次日期"],
        },
    },
    "game_session_finish": {
        "required_params": ["game_session_id"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "game_session_id": {
                "query_tool": "query_game_sessions",
                "extract_by": "customer_name",
                "extra_filter": {"status": "active"},
                "description": "进行中的场次ID",
            },
        },
        "user_input": [],
        "confirm_template": {
            "title": "确认结束游玩",
            "message": "确定要结束游玩吗？",
            "details": ["顾客", "套餐", "开始时间"],
        },
    },
    "material_inbound": {
        "required_params": ["material_id", "quantity"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "material_id": {
                "query_tool": "query_inventory",
                "extract_by": "name",
                "description": "物料ID",
            },
        },
        "user_input": ["quantity"],
        "confirm_template": {
            "title": "确认入库",
            "message": "确定要入库吗？",
            "details": ["物料名称", "入库数量", "当前库存"],
        },
    },
    "material_outbound": {
        "required_params": ["material_id", "quantity"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "material_id": {
                "query_tool": "query_inventory",
                "extract_by": "name",
                "description": "物料ID",
            },
        },
        "user_input": ["quantity"],
        "confirm_template": {
            "title": "确认出库",
            "message": "确定要出库吗？",
            "details": ["物料名称", "出库数量", "当前库存"],
        },
    },
    "reply_feedback": {
        "required_params": ["feedback_id", "reply_content"],
        "pre_filled": ["shop_id"],
        "from_query": {
            "feedback_id": {
                "query_tool": "query_feedbacks",
                "extract_by": "context",   # 从上下文获取最近的评价
                "extra_filter": {"status": "pending"},
                "description": "评价ID",
            },
        },
        "user_input": ["reply_content"],
        "confirm_template": {
            "title": "确认回复评价",
            "message": "确定要回复这条评价吗？",
            "details": ["评价内容"],
        },
    },
    "send_notification": {
        "required_params": ["recipient_ids", "title", "content"],
        "pre_filled": ["shop_id", "recipient_type"],
        "from_query": {
            "recipient_ids": {
                "query_tool": "query_customer" if "customer" else "query_staff_list",
                "extract_by": "all_or_name",
                "description": "接收者ID列表",
                "concat": True,
            },
        },
        "user_input": ["title", "content"],
        "confirm_template": {
            "title": "发送通知",
            "message": "请填写通知内容：",
            "details": ["接收者类型", "接收人数"],
        },
    },
}
