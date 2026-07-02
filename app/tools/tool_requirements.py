"""
工具参数需求定义（结构化版本）

每个操作工具的详细参数需求描述，供 Agent Loop 使用。
LLM 根据此描述自主规划如何获取参数值。

结构说明：
- params: 每个参数的类型、描述、提取方式
- strategies: 获取参数的策略（优先级从高到低）
- fallback: 兜底方案

extract 模式：
- "first": 从查询结果中提取第一个 ID
- "all_concat": 提取所有 ID，逗号拼接为字符串
- "value": 直接使用值
"""

# 查询工具能力描述（供 Agent Loop prompt 使用）
QUERY_TOOLS_DESCRIPTION = """
可用的数据获取方式：

1. query_coupons(status?)
   - 查询优惠券列表
   - 参数: status (可选): active=启用, disabled=禁用
   - 不传参数返回所有优惠券
   - 不支持按名称搜索（需要用 NL2SQL）

2. query_customer(keyword)
   - 搜索顾客信息
   - 参数: keyword (必填): 姓名或手机号
   - 不支持查询所有顾客（需要用 NL2SQL）

3. NL2SQL
   - 用自然语言描述查询需求，系统自动生成 SQL 并执行
   - 适用于任何查询条件
   - 例如: "查询名称包含满100减15的优惠券ID"
   - 例如: "查询所有顾客的ID"
   - 例如: "查询ID为29、39、44的顾客"
"""

# ==================== 操作工具参数需求 ====================

TOOL_REQUIREMENTS = {
    "grant_coupon": {
        "description": "发放优惠券给顾客",
        "params": {
            "coupon_id": {
                "type": "int",
                "description": "优惠券ID",
                "extract": "first",  # 从查询结果中提取第一个 ID
                "required": True,
            },
            "customer_ids": {
                "type": "str",
                "description": "顾客ID列表，逗号分隔（如 '1,2,3'），或 'ALL' 表示所有顾客",
                "extract": "all_concat",  # 提取所有 ID，逗号拼接
                "required": True,
            },
        },
        "strategies": """
获取 coupon_id：
1. 从用户消息中提取优惠券名称
2. 用 NL2SQL 查询: "查询名称包含xxx的优惠券ID"
3. 如果找到 1 条 → 使用该 coupon_id
4. 如果找到多条 → 返回列表让用户选择
5. 如果没找到 → 查询所有优惠券让用户选择

获取 customer_ids：
1. 判断用户意图：
   - 用户说"所有"/"全部"/"全体" → 用 NL2SQL 查询所有顾客: "查询所有顾客的ID"
   - 用户指定姓名 → 用 NL2SQL 查询: "查询姓名包含xxx的顾客ID"
   - 用户说"除了X之外" → 查询全部 → 排除X的ID
   - 用户说"张三和李四" → 分别查询 → 合并 ID
2. 如果找到 → 拼接 ID 为 "1,2,3,..."
3. 如果没找到 → 查询所有顾客让用户选择
""",
        "fallback": "如果某个参数实在无法确定，可以留空，工具会自己弹窗让用户填。允许参数不齐全。",
    },

    "refund_reject": {
        "description": "拒绝退款申请",
        "params": {
            "refund_id": {
                "type": "str",
                "description": "退款记录ID（多个用逗号分隔）",
                "extract": "all_concat",
                "required": True,
            },
            "reason": {
                "type": "str",
                "description": "拒绝原因",
                "extract": "value",  # 直接从用户消息中提取
                "required": True,
            },
        },
        "strategies": """
获取 refund_id：
1. 从用户消息中提取顾客名
2. 用 NL2SQL 查询: "查询顾客xxx的待处理退款记录ID"
3. 如果找到 1 条 → 使用该 refund_id
4. 如果找到多条 → 全部返回（逗号分隔），工具会批量处理
5. 如果没找到 → 查询所有待处理退款让用户选择

获取 reason：
1. 从用户消息中提取拒绝原因
2. 如果用户说了原因 → 直接使用
3. 如果用户没说 → 留空，工具会弹窗让用户填
""",
        "fallback": "如果 refund_id 无法确定，查询所有待处理退款让用户选择。reason 可以留空。",
    },

    "refund_approve": {
        "description": "批准退款申请",
        "params": {
            "refund_id": {
                "type": "str",
                "description": "退款记录ID（多个用逗号分隔）",
                "extract": "all_concat",
                "required": True,
            },
        },
        "strategies": """
获取 refund_id：
1. 从用户消息中提取顾客名
2. 用 NL2SQL 查询: "查询顾客xxx的待处理退款记录ID"
3. 如果找到 1 条 → 使用该 refund_id
4. 如果找到多条 → 全部返回（逗号分隔），工具会批量处理
5. 如果没找到 → 查询所有待处理退款让用户选择
""",
        "fallback": "如果 refund_id 无法确定，查询所有待处理退款让用户选择。",
    },

    "game_session_checkin": {
        "description": "核销入座（开始游玩）",
        "params": {
            "customer_id": {
                "type": "int",
                "description": "顾客ID",
                "extract": "first",
                "required": True,
            },
            "customer_session_id": {
                "type": "int",
                "description": "可用的场次ID",
                "extract": "first",
                "required": True,
            },
        },
        "strategies": """
获取 customer_id 和 customer_session_id：
1. 从用户消息中提取顾客名
2. 用 NL2SQL 查询: "查询顾客xxx的进行中的游玩场次ID和顾客ID"
3. 如果找到 1 条 → 同时获取两个 ID
4. 如果找到多条 → 返回列表让用户选择
5. 如果没找到 → 查询所有进行中的场次让用户选择
""",
        "fallback": "如果无法确定，查询所有进行中的场次让用户选择。",
    },

    "game_session_finish": {
        "description": "结束游玩",
        "params": {
            "game_session_id": {
                "type": "int",
                "description": "进行中的场次ID",
                "extract": "first",
                "required": True,
            },
        },
        "strategies": """
获取 game_session_id：
1. 从用户消息中提取顾客名
2. 用 NL2SQL 查询: "查询顾客xxx的进行中的游戏场次ID"
3. 如果找到 1 条 → 使用该 game_session_id
4. 如果找到多条 → 返回列表让用户选择
5. 如果没找到 → 查询所有进行中的场次让用户选择
""",
        "fallback": "如果无法确定，查询所有进行中的场次让用户选择。",
    },

    "material_inbound": {
        "description": "物料入库",
        "params": {
            "material_id": {
                "type": "int",
                "description": "物料ID",
                "extract": "first",
                "required": True,
            },
            "quantity": {
                "type": "str",
                "description": "入库数量",
                "extract": "value",
                "required": True,
            },
        },
        "strategies": """
获取 material_id：
1. 从用户消息中提取物料名称
2. 用 NL2SQL 查询: "查询名称包含xxx的物料ID"
3. 如果找到 1 条 → 使用该 material_id
4. 如果找到多条 → 返回列表让用户选择
5. 如果没找到 → 查询所有物料让用户选择

获取 quantity：
1. 从用户消息中提取数量（如"100个"→ "100"）
2. 如果用户没说 → 留空，工具会弹窗让用户填
""",
        "fallback": "如果 material_id 无法确定，查询所有物料让用户选择。quantity 可以留空。",
    },

    "material_outbound": {
        "description": "物料出库",
        "params": {
            "material_id": {
                "type": "int",
                "description": "物料ID",
                "extract": "first",
                "required": True,
            },
            "quantity": {
                "type": "str",
                "description": "出库数量",
                "extract": "value",
                "required": True,
            },
        },
        "strategies": """
获取 material_id：
1. 从用户消息中提取物料名称
2. 用 NL2SQL 查询: "查询名称包含xxx的物料ID"
3. 如果找到 1 条 → 使用该 material_id
4. 如果找到多条 → 返回列表让用户选择
5. 如果没找到 → 查询所有物料让用户选择

获取 quantity：
1. 从用户消息中提取数量
2. 如果用户没说 → 留空，工具会弹窗让用户填
""",
        "fallback": "如果 material_id 无法确定，查询所有物料让用户选择。quantity 可以留空。",
    },

    "reply_feedback": {
        "description": "回复顾客评价",
        "params": {
            "feedback_id": {
                "type": "int",
                "description": "评价ID",
                "extract": "first",
                "required": True,
            },
            "reply_content": {
                "type": "str",
                "description": "回复内容",
                "extract": "value",
                "required": True,
            },
        },
        "strategies": """
获取 feedback_id：
1. 从用户消息中提取顾客名
2. 用 NL2SQL 查询: "查询顾客xxx的待回复评价ID"
3. 如果找到 1 条 → 使用该 feedback_id
4. 如果找到多条 → 返回列表让用户选择
5. 如果没找到 → 查询所有待回复评价让用户选择

获取 reply_content：
1. 从用户消息中提取回复内容
2. 如果用户说了 → 直接使用
3. 如果用户没说 → 留空，工具会弹窗让用户填
""",
        "fallback": "如果 feedback_id 无法确定，查询所有待回复评价让用户选择。reply_content 可以留空。",
    },

    "send_notification": {
        "description": "发送通知",
        "params": {
            "recipient_ids": {
                "type": "str",
                "description": "接收者ID列表，逗号分隔",
                "extract": "all_concat",
                "required": True,
            },
            "recipient_type": {
                "type": "str",
                "description": "接收者类型: customer=顾客, staff=员工",
                "extract": "value",
                "required": True,
            },
            "title": {
                "type": "str",
                "description": "通知标题",
                "extract": "value",
                "required": True,
            },
            "content": {
                "type": "str",
                "description": "通知内容",
                "extract": "value",
                "required": True,
            },
        },
        "strategies": """
获取 recipient_type：
- 用户说"顾客"/"客人" → "customer"
- 用户说"员工"/"导玩员" → "staff"
- 无法确定 → 默认 "customer"

获取 recipient_ids：
- 用户说"所有"/"全部" → 用 NL2SQL 查询所有顾客/员工 → 拼接 ID
- 用户指定姓名 → 用 NL2SQL 查询 → 拼接 ID
- 没找到 → 查询所有让用户选择

获取 title 和 content：
- 从用户消息中提取
- 如果用户没说 → 留空，工具会弹窗让用户填
""",
        "fallback": "如果 recipient_ids 无法确定，查询所有接收者让用户选择。title 和 content 可以留空。",
    },
}
