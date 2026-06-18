"""
工具参数需求定义

每个操作工具的详细参数需求描述，供 Agent Loop 使用。
LLM 根据此描述自主规划如何获取参数值。

设计原则：
1. 描述每个参数的含义、类型、获取方式
2. 列出可用的查询工具及其能力
3. 说明每种情况的处理策略（成功/多条/0条）
4. 明确兜底方案：查全部让用户选 / NL2SQL / 留空让工具处理
"""

# 查询工具能力描述（供 Agent Loop prompt 使用）
QUERY_TOOLS_DESCRIPTION = """
可用的查询工具：

1. query_coupons(status?)
   - 查询优惠券列表
   - 参数: status (可选): active=启用, disabled=禁用
   - 不传参数返回所有优惠券
   - 不支持按名称搜索（需要用 NL2SQL）

2. query_customer(keyword)
   - 搜索顾客信息
   - 参数: keyword (必填): 姓名或手机号
   - 不支持查询所有顾客（需要用 NL2SQL: SELECT id, nickname FROM customers WHERE is_deleted=0）
   - 不支持按ID查询（需要用 NL2SQL: SELECT id, nickname FROM customers WHERE id IN (...)）

3. NL2SQL
   - 当查询工具不支持用户的查询条件时，可以用 NL2SQL 直接查询数据库
   - 用自然语言描述查询需求，系统自动生成 SQL
   - 例如: "查询名称包含满100减15的优惠券ID"
   - 例如: "查询所有顾客的ID和昵称"
   - 例如: "查询ID为29、39、44的顾客"
"""

# ==================== 操作工具参数需求 ====================

TOOL_REQUIREMENTS = {
    "grant_coupon": f"""grant_coupon 工具需要以下参数：
- coupon_id (int, 必填): 优惠券ID
- customer_ids (str, 必填): 顾客ID列表，逗号分隔，或 "ALL" 表示所有顾客
- shop_id (int): 系统自动填入，无需处理

## 获取 coupon_id

策略 1：从用户消息中提取优惠券名称
  - 用 NL2SQL 查询: "查询名称包含xxx的优惠券ID"
  - 找到 1 条 → 使用该 coupon_id
  - 找到多条 → 返回列表让用户选择
  - 没找到 → 进入策略 2

策略 2：查询所有优惠券
  - 调用 query_coupons()（不传参数）
  - 返回列表让用户选择

## 获取 customer_ids

策略 1：判断用户意图
  - 用户说"所有"/"全部"/"全体" → 用 NL2SQL 查询所有顾客: "查询所有顾客的ID"
    - 找到 → 拼接 ID 为 "1,2,3,..."
    - 没找到 → 报错"当前没有顾客"
  - 用户指定姓名 → 用 NL2SQL 查询: "查询姓名包含xxx的顾客ID"
    - 找到 1 条 → 使用该 ID
    - 找到多条 → 返回列表让用户选择
    - 没找到 → 进入策略 2
  - 用户说"除了X、Y之外的所有人" → 查询全部 → 排除 X、Y 的 ID
  - 用户说"张三和李四" → 分别查询 → 合并 ID

策略 2：查询所有顾客
  - 用 NL2SQL: "查询所有顾客的ID和昵称"
  - 返回列表让用户选择

## 重要原则
- 每个查询都可能失败，不要假设一定能查到
- 查不到时不要报错，而是提供选项让用户选择
- 用户可能指代不明（如只说"发优惠券"），这是正常的
- 如果某个参数实在无法确定，可以留空，工具会自己弹窗让用户填
- 允许参数不齐全，工具本身就是最后的兜底

{QUERY_TOOLS_DESCRIPTION}
""",

    "refund_reject": f"""refund_reject 工具需要以下参数：
- refund_id (int, 必填): 退款记录ID
- reason (str, 必填): 拒绝原因
- shop_id (int): 系统自动填入，无需处理

## 获取 refund_id

策略 1：从用户消息中提取顾客名
  - 用 NL2SQL 查询: "查询顾客xxx的待处理退款记录ID"
  - 找到 1 条 → 使用该 refund_id
  - 找到多条 → 返回列表让用户选择
  - 没找到 → 进入策略 2

策略 2：查询所有待处理退款
  - 用 NL2SQL: "查询所有待处理的退款记录"
  - 返回列表让用户选择

## 获取 reason

- 从用户消息中提取拒绝原因
- 如果用户说了原因（如"超过退款期限"），直接使用
- 如果用户没说原因，留空，工具会弹窗让用户填

{QUERY_TOOLS_DESCRIPTION}
""",

    "refund_approve": f"""refund_approve 工具需要以下参数：
- refund_id (int, 必填): 退款记录ID
- shop_id (int): 系统自动填入，无需处理

## 获取 refund_id

策略 1：从用户消息中提取顾客名
  - 用 NL2SQL 查询: "查询顾客xxx的待处理退款记录ID"
  - 找到 1 条 → 使用该 refund_id
  - 找到多条 → 返回列表让用户选择
  - 没找到 → 进入策略 2

策略 2：查询所有待处理退款
  - 用 NL2SQL: "查询所有待处理的退款记录"
  - 返回列表让用户选择

{QUERY_TOOLS_DESCRIPTION}
""",

    "game_session_checkin": f"""game_session_checkin 工具需要以下参数：
- customer_id (int, 必填): 顾客ID
- customer_session_id (int, 必填): 可用场次ID
- shop_id (int): 系统自动填入，无需处理

## 获取 customer_id 和 customer_session_id

这两个参数通常一起获取：
1. 从用户消息中提取顾客名
2. 用 NL2SQL 查询: "查询顾客xxx的进行中的游玩场次ID和顾客ID"
3. 找到 1 条 → 同时获取 customer_id 和 customer_session_id
4. 找到多条 → 返回列表让用户选择
5. 没找到 → 查询所有进行中的场次让用户选择

{QUERY_TOOLS_DESCRIPTION}
""",

    "game_session_finish": f"""game_session_finish 工具需要以下参数：
- game_session_id (int, 必填): 进行中的场次ID
- shop_id (int): 系统自动填入，无需处理

## 获取 game_session_id

策略 1：从用户消息中提取顾客名
  - 用 NL2SQL 查询: "查询顾客xxx的进行中的游戏场次ID"
  - 找到 1 条 → 使用该 game_session_id
  - 找到多条 → 返回列表让用户选择
  - 没找到 → 进入策略 2

策略 2：查询所有进行中的场次
  - 用 NL2SQL: "查询所有进行中的游戏场次"
  - 返回列表让用户选择

{QUERY_TOOLS_DESCRIPTION}
""",

    "material_inbound": f"""material_inbound 工具需要以下参数：
- material_id (int, 必填): 物料ID
- quantity (str, 必填): 入库数量
- shop_id (int): 系统自动填入，无需处理

## 获取 material_id

策略 1：从用户消息中提取物料名称
  - 用 NL2SQL 查询: "查询名称包含xxx的物料ID"
  - 找到 1 条 → 使用该 material_id
  - 找到多条 → 返回列表让用户选择
  - 没找到 → 进入策略 2

策略 2：查询所有物料
  - 用 NL2SQL: "查询所有物料的ID和名称"
  - 返回列表让用户选择

## 获取 quantity

- 从用户消息中提取数量（如"100个"→ 100）
- 如果用户没说数量，留空，工具会弹窗让用户填

{QUERY_TOOLS_DESCRIPTION}
""",

    "material_outbound": f"""material_outbound 工具需要以下参数：
- material_id (int, 必填): 物料ID
- quantity (str, 必填): 出库数量
- shop_id (int): 系统自动填入，无需处理

## 获取 material_id

策略 1：从用户消息中提取物料名称
  - 用 NL2SQL 查询: "查询名称包含xxx的物料ID"
  - 找到 1 条 → 使用该 material_id
  - 找到多条 → 返回列表让用户选择
  - 没找到 → 进入策略 2

策略 2：查询所有物料
  - 用 NL2SQL: "查询所有物料的ID和名称"
  - 返回列表让用户选择

## 获取 quantity

- 从用户消息中提取数量
- 如果用户没说数量，留空，工具会弹窗让用户填

{QUERY_TOOLS_DESCRIPTION}
""",

    "reply_feedback": f"""reply_feedback 工具需要以下参数：
- feedback_id (int, 必填): 评价ID
- reply_content (str, 必填): 回复内容
- shop_id (int): 系统自动填入，无需处理

## 获取 feedback_id

策略 1：从用户消息中提取顾客名
  - 用 NL2SQL 查询: "查询顾客xxx的待回复评价ID"
  - 找到 1 条 → 使用该 feedback_id
  - 找到多条 → 返回列表让用户选择
  - 没找到 → 进入策略 2

策略 2：查询所有待回复评价
  - 用 NL2SQL: "查询所有待回复的评价"
  - 返回列表让用户选择

## 获取 reply_content

- 从用户消息中提取回复内容
- 如果用户没说回复什么，留空，工具会弹窗让用户填

{QUERY_TOOLS_DESCRIPTION}
""",

    "send_notification": f"""send_notification 工具需要以下参数：
- recipient_ids (str, 必填): 接收者ID列表，逗号分隔
- recipient_type (str, 必填): 接收者类型，customer=顾客，staff=员工
- title (str, 必填): 通知标题
- content (str, 必填): 通知内容
- shop_id (int): 系统自动填入，无需处理

## 获取 recipient_type

- 用户说"顾客"/"客人" → "customer"
- 用户说"员工"/"导玩员" → "staff"
- 无法确定 → 默认 "customer"

## 获取 recipient_ids

根据 recipient_type 选择查询方式：

如果 recipient_type=customer:
  - 用户说"所有"/"全部" → 用 NL2SQL 查询所有顾客: "查询所有顾客的ID"
  - 用户指定姓名 → 用 NL2SQL: "查询姓名包含xxx的顾客ID"
  - 没找到 → 查询所有顾客让用户选择

如果 recipient_type=staff:
  - 用户说"所有"/"全部" → 用 NL2SQL 查询所有员工: "查询所有员工的ID"
  - 用户指定姓名 → 用 NL2SQL: "查询姓名包含xxx的员工ID"
  - 没找到 → 查询所有员工让用户选择

## 获取 title 和 content

- 从用户消息中提取标题和内容
- 如果用户说了完整的通知内容，提取为 content
- 如果用户没说，留空，工具会弹窗让用户填

{QUERY_TOOLS_DESCRIPTION}
""",
}
