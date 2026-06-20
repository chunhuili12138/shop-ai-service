"""
智能路由模块（优化版）
使用 LLM 一次性完成问题理解和任务分配
"""

import json
import hashlib
from typing import Dict, Any, Optional, List
from app.llm import get_chat_llm
from app.multi_agent.protocol import TaskPlan, TaskComplexity, AgentType, SubTask, AgentResult
from app.utils.json_parser import safe_parse_json
from app.skills.manager import get_skill_manager


# 计划缓存（内存缓存，相似问题复用）
_plan_cache = {}
_cache_max_size = 100


def _get_cache_key(task: str, shop_context: str = "") -> str:
    """生成缓存键"""
    # 移除空格和标点，生成相似问题的相同 key
    import re
    normalized = re.sub(r'[^\w\u4e00-\u9fff]', '', task + shop_context)
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


# 任务路由和计划生成合并 Prompt
COMPLEXITY_PROMPT = """你是「店铺智能助手」，专为 DIY 手工店、亲子游乐等体验式门店设计的 AI 运营助手。你的职责是帮助店长管理店铺运营、查询数据、分析经营状况。

分析用户问题，判断处理方式并生成执行计划。

用户问题：{task}

## 重要：理解省略句和上下文

当用户的问题是简短的省略句时（如"本月呢？"、"那昨天呢？"），必须结合【上下文信息】中的历史对话来理解用户的真实意图。

当用户的问题是关于之前对话内容的追问时（如"这个是什么意思？"、"你输出的这个是什么？"），这是**上下文相关问题**，应该使用 **llm** Agent 处理。

示例：
- 历史对话：用户问"历史总收入"，助手回答"¥879.49"
- 当前问题："本月呢？"
- 正确理解："本月的收入是多少？"（而不是"本月的运营数据"）
- 路由：single + nl2sql

- 历史对话：助手返回了"总费用: ¥62945.00"
- 当前问题："这个总费用是支出吗？"
- 正确理解：用户在追问之前回答中的术语含义
- 路由：single + llm（基于上下文回答，不需要查询数据）

- 历史对话：用户问"今天有多少顾客"，助手回答"15人"
- 当前问题："那昨天呢？"
- 正确理解："昨天有多少顾客？"
- 路由：single + nl2sql

可用 Agent：
- rag: 知识问答（定义、解释、建议、规则、方法论、实时信息等）
- nl2sql: 数据查询（营业额、顾客数、库存、员工绩效等具体数据）
- tool: 工具调用（执行具体操作或查询，**必须使用下面的 tool 名称**）
- llm: 上下文分析、追问解释、总结建议（基于已有信息回答，不需要查询数据）
- vision: 图像理解（OCR文字识别、图像分析等）

## 可用 Tool 名称（tool agent 必须从以下名称中选择，禁止生成其他名称）

**查询工具**：
- query_revenue: 查询营收数据
- query_packages: 查询套餐列表
- query_top_packages: 查询热销套餐排行
- query_customer: 查询顾客信息
- query_purchases: 查询购买记录
- query_game_sessions: 查询核销/游玩记录
- query_refunds: 查询退款记录
- query_inventory: 查询库存
- query_low_stock: 查询低库存预警
- query_staff_list: 查询员工列表
- query_staff_performance: 查询员工绩效
- query_coupons: 查询优惠券
- query_coupon_usages: 查询优惠券使用记录
- query_feedbacks: 查询评价反馈
- query_staff_schedules: 查询排班
- query_attendance_records: 查询考勤记录
- query_notifications: 查询通知消息
- query_daily_snapshots: 查询每日经营快照
- query_revenue_trend: 查询营收趋势
- query_operation_logs: 查询操作日志

**操作工具**（执行前会弹出确认框）：
- refund_approve: 审批退款（批准）
- refund_reject: 审批退款（拒绝）
- game_session_checkin: 核销入座
- game_session_finish: 结束游玩
- material_inbound: 物料入库
- material_outbound: 物料出库
- grant_coupon: 发放优惠券
- reply_feedback: 回复评价
- send_notification: 发送通知

**查询工具能力表**（用户的查询条件必须匹配"支持"列才用 tool，否则用 nl2sql）：
- query_customer: 支持 keyword(姓名/手机号) | 不支持: 按ID查、按标签、按日期范围
- query_purchases: 支持 customer_id, status(valid/refunded/expired) | 不支持: 按套餐名、按金额范围、按日期
- query_refunds: 支持 purchase_id, status(pending/completed/rejected) | 不支持: 按顾客名、按金额、按日期
- query_inventory: 支持 keyword(物料名) | 不支持: 按ID、按数量范围、按分类
- query_coupons: 支持 status(active/disabled) | 不支持: 按名称、按类型、按金额
- query_feedbacks: 支持 status(pending/replied) | 不支持: 按顾客名、按内容、按日期
- query_staff_list: 支持 keyword(姓名) | 不支持: 按ID、按角色、按日期
- query_staff_performance: 支持 date_range(today/week/month) | 不支持: 按员工、按指标
- query_staff_schedules: 支持 date, staff_id | 不支持: 按时间段、按状态
- query_attendance_records: 支持 staff_id, date | 不支持: 按状态、按时间段
- query_notifications: 支持 recipient_type(staff/customer) | 不支持: 按标题、按内容、按日期
- query_daily_snapshots: 支持 start_date, end_date | 不支持: 按指标筛选
- query_revenue_trend: 支持 granularity(day/week/month), days | 不支持: 按套餐、按渠道
- query_operation_logs: 支持 operator_id, action, target_type, start_date, end_date
- query_coupon_usages: 支持 customer_id | 不支持: 按优惠券名、按日期
- query_revenue: 支持 date_range(today/week/month/year) | 不支持: 按套餐、按渠道、按金额
- query_packages: 支持 package_type(single/week/month) | 不支持: 按名称、按价格范围
- query_top_packages: 支持 limit | 不支持: 按时间段
- query_low_stock: 无筛选条件，返回所有低库存物料

**使用规则**：
- 用户说"批准退款" → tool: refund_approve
- 用户说"拒绝退款" → tool: refund_reject
- 用户说"核销" → tool: game_session_checkin
- 用户说"查顾客张三"（按名称） → tool: query_customer
- 用户说"查退款记录" → tool: query_refunds
- 用户说"查库存" → tool: query_inventory
- 用户说"入库/出库" → tool: material_inbound / material_outbound
- 用户说"id是29的顾客"（按ID查） → nl2sql（query_customer 不支持按ID查）
- 用户说"昨天退款了多少钱"（按日期查金额） → nl2sql（query_refunds 不支持按日期查金额）
- 用户说"哪些物料库存低于10个"（按数量筛选） → nl2sql（query_inventory 不支持按数量筛选）
- 用户说"本月新注册的顾客"（按日期筛选） → nl2sql（query_customer 不支持按日期筛选）
- 禁止生成如"上下文理解"、"数据查询"、"工具调用"等描述性名称

## 判断规则（按优先级）

### 0. tool 和 nl2sql 的区别（重要！）
- **tool**: 直接调用预定义工具函数，精确执行。当用户的问题有对应的 tool 名**且查询条件匹配工具支持的参数**时，使用 tool
  - "查退款" → tool: query_refunds（无筛选条件，返回默认列表）
  - "批准退款" → tool: refund_approve
  - "查顾客张三" → tool: query_customer（keyword 匹配）
  - "查库存" → tool: query_inventory
- **nl2sql**: 需要 LLM 生成 SQL 查询数据库。当用户的查询条件**不匹配任何工具支持的参数**时使用
  - "id是29的顾客" → nl2sql（query_customer 不支持按ID查）
  - "昨天退款了多少钱" → nl2sql（query_refunds 不支持按日期查金额）
  - "哪些物料库存低于10个" → nl2sql（query_inventory 不支持按数量筛选）
  - "本月营业额趋势" → nl2sql（需要聚合查询）
  - "哪些套餐卖得最好" → nl2sql（需要聚合查询）
  - 参考上方的【查询工具能力表】判断

### 1. 上下文相关问题 → single + llm
用户在追问之前对话中的内容，或询问术语含义：
- "这个是什么意思？"
- "你输出的这个是支出吗？"
- "为什么是这个数字？"
- "能解释一下吗？"

### 2. 知识性问题 → single + rag
不需要查询店铺数据，只需要知识库或通用商业知识回答：
- 定义/解释类："什么是优质客户？"、"如何定义VIP会员？"
- 建议/方法类："如何提高顾客满意度？"、"怎样做好营销？"
- 助手身份类："你是谁？"、"你能做什么？"、"介绍一下自己"
- **套餐价格/详情**："拼豆多少钱？"、"月卡包含什么？"、"套餐有什么？"（知识库有套餐文档）
- **退款政策**："多久可以退款？"、"退款流程是什么？"（知识库有退款文档）
- **营业时间/地址**："几点开门？"、"地址在哪？"、"电话多少？"（知识库有时问文档）
- **店铺规则**："几岁能玩？"、"有什么注意事项？"（知识库有规则文档）
- **助手功能**："你支持什么操作？"、"你能帮我做什么？"（知识库有功能介绍）

**重要区分**：
- "套餐多少钱？" → rag（查知识库 `packages.md`，不是查数据库）
- "本月卖了多少套餐？" → nl2sql（查数据库聚合数据）
- "退款政策是什么？" → rag（查知识库 `refund.md`）
- "有哪些退款申请？" → tool: query_refunds（查数据库实时数据）

### 3. 数据查询问题 → single + nl2sql 或 single + tool
需要查询当前店铺的具体数据：
- 查询类："今天营业额多少？"、"有多少顾客？"
- 统计类："本月销售排名？"、"库存还有多少？"
- 省略句：结合历史对话理解（如"本月呢？" → "本月的收入"）
- 顾客查询："查一下顾客XXX" → tool: query_customer
- 退款查询："退款记录" → tool: query_refunds 或 nl2sql

### 4. 操作执行问题 → single + tool
用户要求执行具体操作：
- "批准退款" → tool: refund_approve
- "拒绝退款" → tool: refund_reject
- "核销" → tool: game_session_checkin
- "入库" → tool: material_inbound

### 5. 综合分析问题 → multi
需要先查询数据，再进行分析：
- 分析类："分析本月经营情况"、"为什么业绩下降了？"
- 报告类："生成本月经营报告"

### 6. 不支持的操作 → single + llm（回复用户不支持）
以下操作不在系统能力范围内，必须路由到 llm agent，回复用户"该操作暂不支持，请通过店铺后台管理系统操作"：
- 删除数据：删除顾客、删除订单、删除退款记录、删除套餐
- 修改核心数据：修改价格、修改套餐内容、修改顾客信息、修改订单金额
- 系统管理：修改系统设置、修改权限、添加/删除员工账号
- 外部通信：发送短信、发送微信消息、拨打电话
- 支付操作：发起支付、退款到银行卡（退款仅限系统内审批处理）
- 批量数据操作：批量导入/导出数据、清空数据、数据库操作
- 撤销操作：撤销已执行的退款、撤销核销、回退订单状态

【重要 - 必须严格遵守】当用户请求以上不支持的操作时：
- mode 必须是 single
- agent 必须是 llm（不是 tool！）
- tool_name 不要填写（留空或 null）
- 不要尝试执行任何工具，直接告诉用户不支持该操作

## plan.tool 填写规则（必须严格遵守）
plan 中每个步骤的 tool 字段决定了执行器如何调度，填写错误会导致执行失败：
- agent=rag 时，plan.tool 必须填 "rag"
- agent=nl2sql 时，plan.tool 必须填 "nl2sql"
- agent=llm 时，plan.tool 必须填 "llm"
- agent=tool 时，plan.tool 必须填 TOOL_MAP 中的具体名称（如 query_refunds, refund_approve, query_customer）
- 禁止编造不存在的 tool 名（如 rag_knowledge_retrieval、nl2sql_query、数据查询 等）

## 输出格式

请返回严格的 JSON 格式：

{{
    "mode": "single 或 multi",
    "agent": "rag/nl2sql/tool/llm/vision"（single 模式时）,
    "tool_name": "具体的tool名称"（仅当agent=tool时填写，必须是上面列出的名称）,
    "reasoning": "判断原因",
    "is_knowledge_question": true/false,
    "understanding": "用户想要XXX（如果是省略句或追问，要写出完整意图）",
    "analysis": "分析问题的核心需求",
    "plan": [
        {{
            "step": 1,
            "action": "查询XXX",
            "tool": "rag 或 nl2sql 或 llm 或 具体tool名",
            "is_critical": true
        }}
    ],
    "complexity": "simple/medium/complex"
}}

## 输出示例

示例1 - 知识问答（agent=rag）：
{{"mode": "single", "agent": "rag", "reasoning": "用户问退款政策，属于知识问答", "understanding": "用户想了解退款政策", "analysis": "查询知识库退款文档", "plan": [{{"step": 1, "action": "从知识库检索退款政策", "tool": "rag", "is_critical": true}}], "complexity": "simple"}}

示例2 - 数据查询（agent=nl2sql）：
{{"mode": "single", "agent": "nl2sql", "reasoning": "用户查询营业额，需要查数据库", "understanding": "用户想查询本月营业额", "analysis": "查询 purchases 表", "plan": [{{"step": 1, "action": "查询本月营业额", "tool": "nl2sql", "is_critical": true}}], "complexity": "simple"}}

示例3 - 工具操作（agent=tool）：
{{"mode": "single", "agent": "tool", "tool_name": "refund_reject", "reasoning": "用户要拒绝退款", "understanding": "用户要拒绝猪八戒的退款", "analysis": "调用退款拒绝工具", "plan": [{{"step": 1, "action": "拒绝退款", "tool": "refund_reject", "is_critical": true}}], "complexity": "simple"}}

示例4 - 不支持的操作：
{{"mode": "single", "agent": "llm", "reasoning": "删除数据不在系统能力范围", "understanding": "用户想删除顾客数据", "analysis": "不支持的操作", "plan": [{{"step": 1, "action": "告知用户不支持", "tool": "llm", "is_critical": true}}], "complexity": "simple"}}

## 重要：输出格式要求
1. 你必须只返回一个完整的 JSON 对象，不要包含任何其他文字、解释或 markdown 代码块标记（不要用 ```json ```）
2. JSON 必须是有效的格式，所有字符串必须用双引号
3. 不要在 JSON 前后添加任何文字
4. 如果你不确定如何判断，也必须返回一个有效的 JSON（可以使用默认值）

请直接返回 JSON："""


# 执行计划生成提示词
PLAN_GENERATION_PROMPT = """你是一个任务规划专家。根据用户问题，制定详细的执行计划。

## 用户问题
{task}

## 可用工具
- **知识检索**：查询知识库获取店铺规则、产品信息、行业知识等
- **数据查询**：查询数据库获取营业额、顾客数、库存等统计数据
- **工具调用**：执行特定操作（查询顾客信息、排班表、优惠券等）
- **互联网搜索**：获取实时信息（新闻、天气、汇率等）

## 规划原则

1. **分解复杂任务**：将复杂问题分解为多个可执行的子步骤
2. **明确每步目标**：每个步骤都要有明确的目标和预期输出
3. **识别依赖关系**：标明哪些步骤依赖其他步骤的结果
4. **判断关键步骤**：标记哪些步骤是核心步骤，失败会影响后续

## 输出格式

请返回严格的 JSON 格式，不要添加任何额外文本：

{{
    "understanding": "用户想要XXX（对问题的理解）",
    "analysis": "分析问题的核心需求和解决思路",
    "plan": [
        {{
            "step": 1,
            "action": "查询XXX",
            "tool": "数据查询",
            "purpose": "获取XXX数据",
            "expected": "预期获得XXX",
            "is_critical": true,
            "depends_on": []
        }}
    ],
    "expected_result": "最终预期输出XXX",
    "complexity": "simple/medium/complex"
}}

## 示例

### 示例 1：简单查询
用户问题：今天营业额多少

输出：
{{
    "understanding": "用户想要查询今天的营业额",
    "analysis": "这是一个简单的数据查询问题，直接查询今日销售数据即可",
    "plan": [
        {{
            "step": 1,
            "action": "查询今日销售数据",
            "tool": "nl2sql",
            "purpose": "获取今日所有订单的销售总额",
            "expected": "获得今日营业额数字",
            "is_critical": true,
            "depends_on": []
        }}
    ],
    "expected_result": "今日营业额的具体数字",
    "complexity": "simple"
}}

### 示例 2：复杂分析
用户问题：分析本月经营情况并给出改进建议

输出：
{{
    "understanding": "用户想要全面分析本月的经营状况，并获得改进建议",
    "analysis": "需要从多个维度分析经营数据，包括销售、顾客、支出等，然后综合分析并给出建议",
    "plan": [
        {{
            "step": 1,
            "action": "查询本月销售数据",
            "tool": "nl2sql",
            "purpose": "获取本月销售额、订单数、热销套餐等",
            "expected": "获得本月销售汇总数据",
            "is_critical": true,
            "depends_on": []
        }},
        {{
            "step": 2,
            "action": "查询本月顾客数据",
            "tool": "nl2sql",
            "purpose": "获取本月新顾客数、活跃顾客数等",
            "expected": "获得本月顾客统计",
            "is_critical": true,
            "depends_on": []
        }},
        {{
            "step": 3,
            "action": "查询本月支出数据",
            "tool": "nl2sql",
            "purpose": "获取本月各类支出明细",
            "expected": "获得本月支出汇总",
            "is_critical": true,
            "depends_on": []
        }},
        {{
            "step": 4,
            "action": "综合分析经营情况",
            "tool": "llm",
            "purpose": "分析销售、顾客、支出数据，找出问题和机会",
            "expected": "得出经营分析结论",
            "is_critical": true,
            "depends_on": [1, 2, 3]
        }},
        {{
            "step": 5,
            "action": "生成改进建议",
            "tool": "llm",
            "purpose": "基于分析结果，给出具体可行的改进建议",
            "expected": "提供3-5条改进建议",
            "is_critical": false,
            "depends_on": [4]
        }}
    ],
    "expected_result": "完整的本月经营分析报告和改进建议",
    "complexity": "complex"
}}

请严格按照上述格式返回 JSON，不要添加任何额外文本。"""


# 任务拆分提示词（支持依赖关系）
TASK_SPLIT_PROMPT = """分析以下复杂任务，将其拆分成多个子任务，并指定子任务之间的依赖关系。

任务：{task}

## 可用 Agent 类型：
- nl2sql: 数据查询（营业额、顾客数、库存、员工绩效、财务数据等）
- tool: 工具调用（查询顾客信息、排班表、优惠券等）
- llm: 总结分析建议（基于数据进行分析、总结、给出建议）
- rag: 知识问答（定义、解释、行业知识、规则政策等）
- vision: 图像理解（OCR文字识别、图像分析等）

## 操作类工具（agent=tool 时必须指定 tool_name）
- refund_approve: 批准退款
- refund_reject: 拒绝退款
- game_session_checkin: 核销入座
- game_session_finish: 结束游玩
- material_inbound: 物料入库
- material_outbound: 物料出库
- grant_coupon: 发放优惠券
- reply_feedback: 回复评价
- send_notification: 发送通知

## 重要规则（必须遵守）

### Agent 选择规则
1. **查询店铺数据** → 使用 nl2sql（营业额、订单、顾客、库存等）
2. **分析/总结/建议** → 使用 llm（基于数据进行分析、给出建议）
3. **知识问答** → 使用 rag（定义、解释、行业知识、规则政策）
4. **工具操作** → 使用 tool（必须指定 tool_name）

### tool_name 填写规则
- agent="tool" 时，必须指定 tool_name（从上面的操作类工具列表中选择）
- agent 不是 "tool" 时，tool_name 填空字符串 ""

### 拆分规则
1. 每个子任务应该明确指定使用哪个 Agent
2. 子任务之间应该清晰分离，避免重复
3. 保持原始任务的语义，不要遗漏信息
4. 如果子任务之间有依赖关系，必须指定 depends_on
5. 查询类子任务应该放在操作类子任务之前

## 示例

示例1（经营分析）：
任务："分析本月经营情况"
拆分结果：
[
    {{"id": 1, "task": "查询本月营收数据", "agent": "nl2sql", "tool_name": "", "description": "查询本月营业额、订单数、热销套餐", "depends_on": []}},
    {{"id": 2, "task": "查询本月顾客数据", "agent": "nl2sql", "tool_name": "", "description": "查询本月新顾客数、活跃顾客数", "depends_on": []}},
    {{"id": 3, "task": "查询本月支出数据", "agent": "nl2sql", "tool_name": "", "description": "查询本月各类支出", "depends_on": []}},
    {{"id": 4, "task": "汇总分析并给出建议", "agent": "llm", "tool_name": "", "description": "基于以上数据进行分析并给出建议", "depends_on": [1, 2, 3]}}
]

示例2（操作类任务）：
任务："黄晓明的审核通过，赵丽颖的审核拒绝"
拆分结果：
[
    {{"id": 1, "task": "查询黄晓明和赵丽颖的待处理退款信息", "agent": "nl2sql", "tool_name": "", "description": "获取退款记录ID", "depends_on": []}},
    {{"id": 2, "task": "批准黄晓明的退款", "agent": "tool", "tool_name": "refund_approve", "description": "调用退款批准工具", "depends_on": [1]}},
    {{"id": 3, "task": "拒绝赵丽颖的退款", "agent": "tool", "tool_name": "refund_reject", "description": "调用退款拒绝工具", "depends_on": [1]}}
]

示例3（混合任务）：
任务："查询本月业绩，然后批准黄晓明的退款"
拆分结果：
[
    {{"id": 1, "task": "查询本月业绩数据", "agent": "nl2sql", "tool_name": "", "description": "查询本月的营业额和订单数", "depends_on": []}},
    {{"id": 2, "task": "批准黄晓明的退款", "agent": "tool", "tool_name": "refund_approve", "description": "调用退款批准工具", "depends_on": [1]}}
]

请返回 JSON 格式的数组：
[
    {{"id": 1, "task": "子任务描述", "agent": "agent类型", "tool_name": "工具名（agent=tool时必填，否则填空字符串）", "description": "任务说明", "depends_on": []}},
    ...
]

## 重要：JSON 格式要求
1. 必须使用双引号，不能使用单引号
2. 不能添加注释
3. 不能添加多余的文字
4. 只返回纯 JSON 数组，不要包含 markdown 代码块

请直接返回 JSON 数组:"""


class TaskRouter:
    """
    智能路由（优化版）
    
    使用 LLM 判断问题类型，避免关键词匹配的局限性
    规则：
    1. 上下文相关问题 → LLM Agent
    2. 知识性问题 → RAG Agent
    3. 数据查询问题 → NL2SQL Agent
    4. 工具操作问题 → Tool Agent
    5. 复杂问题 → Supervisor（多 Agent 协作）
    """
    
    # 上下文相关关键词（这些词通常表示用户在追问之前的内容）
    CONTEXT_KEYWORDS = [
        "这个", "那个", "它", "上面", "之前", "刚才",
        "是什么意思", "为什么", "能解释",
        "是吗", "对吗", "吗",
        "重新回答", "再回答", "换个方式",
    ]
    
    def __init__(self):
        self._llm = None
    
    @property
    def llm(self):
        """懒加载 LLM"""
        if self._llm is None:
            self._llm = get_chat_llm()
        return self._llm
    
    async def _check_need_clarification(self, question: str, shop_name: str = "", history_context: str = "") -> dict:
        """
        检查是否需要追问
        
        Args:
            question: 用户问题
            shop_name: 店铺名称（有店铺则跳过店铺相关追问）
            history_context: 对话历史上下文
        
        Returns:
            {"need_clarify": bool, "reason": str, "missing_info": str, "clarify_message": str, "quick_questions": list}
        """
        question = question.strip()
        
        # 快速问题示例
        default_quick_questions = [
            "今天营业额多少？",
            "本月经营情况如何？",
            "有哪些套餐？",
            "库存还有多少？",
        ]
        
        # 1. 规则判断：已有店铺上下文，跳过店铺相关追问
        if shop_name:
            # 检查是否是店铺内部问题（不需要追问）
            shop_internal_keywords = [
                "营业", "开门", "关门", "下班", "打烊", "几点",
                "套餐", "价格", "退款", "库存", "物料", "员工", "排班",
                "营业额", "收入", "支出", "顾客", "会员",
            ]
            if any(kw in question for kw in shop_internal_keywords):
                return {
                    "need_clarify": False,
                    "reason": "店铺内部问题，无需追问",
                    "missing_info": "",
                    "clarify_message": "",
                    "quick_questions": []
                }
        
        # 2. 规则判断：模糊指代
        vague_keywords = ["这个", "那个", "它", "他们", "这些", "那些"]
        if any(kw == question or question.startswith(kw) for kw in vague_keywords):
            return {
                "need_clarify": True,
                "reason": "指代不明",
                "missing_info": "具体对象",
                "clarify_message": "请问您指的是什么？",
                "quick_questions": default_quick_questions
            }
        
        # 3. LLM 判断（复杂情况）
        try:
            history_section = ""
            if history_context:
                history_section = f"""
## 对话历史
{history_context}
"""

            prompt = f"""判断用户问题是否需要追问才能准确回答。

用户问题："{question}"
{history_section}
判断规则：
1. 先查看对话历史，理解用户的上下文
2. 如果用户的问题可以从对话历史中推断出含义，不需要追问
3. 如果用户的问题是对之前回答的纠正或确认，不需要追问
4. 只有当问题完全无法从上下文理解时，才需要追问

需要追问的情况：
1. 问题缺少关键信息，且对话历史中也没有
2. 问题有多种理解方式，无法从上下文推断
3. 问题涉及全新的主题，与历史对话无关

不需要追问的情况：
1. 问题可以从对话历史中推断出含义
2. 问题是对之前回答的纠正或确认
3. 问题涉及店铺内部数据（营业额、退款、库存等）
4. 问题是通用知识

只返回 JSON 格式：
{{"need_clarify": true/false, "reason": "原因", "missing_info": "缺少的信息"}}"""
            
            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            from app.utils.json_parser import safe_parse_json
            result = safe_parse_json(response.content.strip())
            
            if result and isinstance(result, dict):
                result["clarify_message"] = self._generate_clarification_message(question, result.get("missing_info", ""))
                result["quick_questions"] = default_quick_questions
                return result
            
            return {"need_clarify": False, "reason": "", "missing_info": "", "clarify_message": "", "quick_questions": []}
        except Exception as e:
            print(f"[Router] 追问检查失败: {str(e)}")
            return {"need_clarify": False, "reason": "", "missing_info": "", "clarify_message": "", "quick_questions": []}
    
    def _generate_clarification_message(self, question: str, missing_info: str) -> str:
        """
        生成追问消息
        
        Args:
            question: 用户问题
            missing_info: 缺少的信息
        
        Returns:
            追问消息
        """
        if "地点" in missing_info or "位置" in missing_info or "哪里" in missing_info:
            return f"请问您想了解哪个地方？"
        elif "套餐" in missing_info:
            return "请问您想了解哪个套餐？"
        elif "时间" in missing_info:
            return "请问您想了解哪个时间段？"
        else:
            return f"为了更准确地回答您的问题，请补充：{missing_info}"
    
    async def _check_question_validity(self, question: str, history_context: str = "") -> dict:
        """
        检查问题是否有效（不是无意义内容）
        
        Args:
            question: 用户问题
            history_context: 对话历史上下文
        
        Returns:
            {"is_valid": bool, "reason": str, "suggestion": str, "quick_questions": list}
        """
        # 快速规则检查
        question = question.strip()
        
        # 默认快捷问题
        default_quick_questions = [
            "今天营业额多少？",
            "本月经营情况如何？",
            "有哪些套餐？",
            "库存还有多少？",
        ]
        
        # 1. 太短的问题（可能是无意义输入）
        if len(question) < 2:
            return {
                "is_valid": False,
                "reason": "问题太短",
                "suggestion": "我没有理解您的意思，请问您想了解什么？",
                "quick_questions": default_quick_questions
            }
        
        # 2. 纯数字或特殊字符
        import re
        if re.match(r'^[\d\s\.\+\-\*\/\=\!\@\#\$\%\^\&\(\)]+$', question):
            return {
                "is_valid": False,
                "reason": "纯数字或特殊字符输入",
                "suggestion": "我没有理解您的意思，请问您想了解什么？",
                "quick_questions": default_quick_questions
            }
        
        # 3. 单个字符重复
        if len(set(question.replace(' ', ''))) == 1:
            return {
                "is_valid": False,
                "reason": "无意义的重复字符",
                "suggestion": "我没有理解您的意思，请问您想了解什么？",
                "quick_questions": default_quick_questions
            }
        
        # 4. 使用 LLM 判断问题是否有效
        try:
            history_section = ""
            if history_context:
                history_section = f"""
## 对话历史
{history_context}
"""

            prompt = f"""判断以下用户输入是否是一个有效的问题或请求。

用户输入："{question}"
{history_section}
有效的输入：
- 有明确意图的问题（如"今天营业额多少"）
- 有明确意图的请求（如"帮我查一下库存"、"同意林志玲退款"、"拒绝黄晓明的退款"）
- 基于对话历史的纠正或确认（如"处理中不就是待处理嘛"）
- 简短但有意义的问候（如"你好"、"在吗"）

无效的输入：
- 无意义的字符（如"111"、"aaa"、"..."）
- 测试输入（如"test"、"测试"）
- 不完整的输入（如"帮我"、"查询"）
- 纯表情符号

判断规则：
1. 如果用户输入可以从对话历史中推断出意图，判定为有效
2. 如果用户输入是操作指令（如批准、拒绝、查询、发放），判定为有效
3. 只有真正无意义的输入才判定为无效

只返回 JSON 格式：
{{"is_valid": true/false, "reason": "原因", "suggestion": "如果无效，给用户的友好反问"}}"""
            
            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            from app.utils.json_parser import safe_parse_json
            result = safe_parse_json(response.content.strip())
            
            if result and isinstance(result, dict):
                # 添加快捷问题
                result["quick_questions"] = default_quick_questions
                # 修改 suggestion 为反问形式
                if not result.get("is_valid") and result.get("suggestion"):
                    if not any(kw in result["suggestion"] for kw in ["请问", "您想", "您需要"]):
                        result["suggestion"] = "我没有理解您的意思，请问您想了解什么？"
                return result
            
            return {"is_valid": True, "reason": "判断失败", "suggestion": "", "quick_questions": []}
        except Exception as e:
            print(f"[Router] 问题有效性检查失败: {str(e)}")
            return {"is_valid": True, "reason": "判断失败", "suggestion": "", "quick_questions": []}
    
    def _is_context_question(self, task: str, history_context: str = "") -> bool:
        """判断是否是上下文相关问题"""
        if not history_context:
            return False
        
        task_lower = task.lower()
        
        # 检查是否包含上下文关键词
        for keyword in self.CONTEXT_KEYWORDS:
            if keyword in task_lower:
                return True
        
        # 检查是否是短问题（可能是省略句）
        if len(task) < 10 and any(kw in history_context for kw in ["用户", "助手"]):
            return True
        
        return False
    
    async def route(self, task: str, has_image: bool = False, shop_context: str = "") -> Dict[str, Any]:
        """
        判断任务路由
        
        流程：
        1. 图像任务 → Vision Agent
        2. 上下文相关问题 → LLM Agent
        3. 问题有效性检查 → 可能返回 clarify
        4. 追问检查 → 可能返回 clarify
        5. LLM 判断任务类型 → COMPLEXITY_PROMPT
        
        Args:
            task: 用户任务
            has_image: 是否包含图像
            shop_context: 店铺上下文信息（行业、套餐等）
        
        Returns:
            路由结果
        """
        # 1. 如果有图像，直接使用 Vision Agent
        if has_image:
            return {
                "mode": "single",
                "agent": AgentType.VISION,
                "reasoning": "包含图像，使用 Vision Agent 处理"
            }
        
        # 2. 提取历史上下文
        history_context = ""
        if shop_context and "历史对话" in shop_context:
            history_context = shop_context
        
        # 3. 上下文相关问题
        if self._is_context_question(task, history_context):
            return {
                "mode": "single",
                "agent": AgentType.LLM,
                "reasoning": "上下文相关问题，使用 LLM 基于历史回答",
                "understanding": "用户在追问之前对话中的内容",
                "analysis": "这是一个上下文相关问题，需要结合历史对话理解",
                "plan": [{"step": 1, "action": "基于上下文回答", "tool": "llm", "is_critical": True}],
                "complexity": "simple"
            }
        
        # 4. 检查问题是否有效（不是无意义内容）
        validity = await self._check_question_validity(task, history_context)
        if not validity.get("is_valid"):
            print(f"[Router] 问题无效: {validity.get('reason')}")
            return {
                "mode": "clarify",
                "agent": None,
                "reasoning": validity.get("reason", "问题不明确"),
                "understanding": task,
                "analysis": "",
                "plan": [],
                "complexity": "simple",
                "clarification": validity.get("suggestion", "我没有理解您的意思，请问您想了解什么？"),
                "quick_questions": validity.get("quick_questions", [])
            }
        
        # 5. 检查是否需要追问
        shop_name = ""
        if shop_context:
            for line in shop_context.split("\n"):
                if "店铺名称" in line:
                    shop_name = line.split("：")[-1].strip() if "：" in line else line.split(":")[-1].strip()
                    break
        
        clarification = await self._check_need_clarification(task, shop_name, history_context)
        if clarification.get("need_clarify"):
            missing_info = clarification.get("missing_info", "")
            print(f"[Router] 需要追问，缺少信息: {missing_info}")
            return {
                "mode": "clarify",
                "agent": None,
                "reasoning": clarification.get("reason", "问题需要更多信息"),
                "understanding": task,
                "analysis": "",
                "plan": [],
                "complexity": "simple",
                "clarification": clarification.get("clarify_message", "请问您想了解什么？"),
                "quick_questions": clarification.get("quick_questions", [])
            }
        
        # 6. 检查缓存
        cache_key = _get_cache_key(task, shop_context)
        if cache_key in _plan_cache:
            print(f"[Router] 命中计划缓存: {cache_key}")
            return _plan_cache[cache_key]
        
        try:
            # 7. 使用 COMPLEXITY_PROMPT 判断任务类型
            from langchain_core.messages import HumanMessage
            
            prompt = COMPLEXITY_PROMPT.format(task=task)
            
            # 添加店铺上下文和历史上下文
            if shop_context:
                prompt += f"\n\n## 上下文信息\n{shop_context}"
            
            # 添加明确指令：如何使用历史上下文
            if shop_context and "历史对话" in shop_context:
                prompt += """

## 重要：处理模糊指代和重试指令

当用户的问题是模糊指代（如"重试上面这个问题"、"再试一次"、"那个呢"）时：
1. 先查看【上下文信息】中的历史对话
2. 找到用户上一个具体的问题
3. 将当前问题理解为那个具体问题

示例：
- 历史对话：用户问"今天营业额多少"，助手回答"¥2,580"
- 当前问题："重试上面这个问题"
- 正确理解：用户想要重新查询"今天营业额多少"
- 路由：single + nl2sql（使用原始问题，而不是"重试"这个指令）

- 历史对话：用户问"今天天气怎么样"，助手追问"请问您想了解哪个地方？"
- 当前问题："嘉善"
- 正确理解：用户想查询"嘉善天气"
- 路由：single + rag
"""
            
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            # 解析响应（处理 markdown 代码块）
            content = response.content.strip()
            
            # 提取 JSON
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()
            
            result = safe_parse_json(content)
            
            # JSON 解析失败时重试
            max_retries = 2
            retry_count = 0
            while not result and retry_count < max_retries:
                retry_count += 1
                print(f"[Router] JSON 解析失败，重试 {retry_count}/{max_retries}")
                retry_prompt = prompt + "\n\n【重要】你上次返回的内容不是有效的 JSON。请严格只返回一个 JSON 对象，不要包含任何其他文字。"
                response = await self.llm.ainvoke([HumanMessage(content=retry_prompt)])
                content = response.content.strip()
                
                if "```json" in content:
                    start = content.find("```json") + 7
                    end = content.find("```", start)
                    content = content[start:end].strip()
                elif "```" in content:
                    start = content.find("```") + 3
                    end = content.find("```", start)
                    content = content[start:end].strip()
                
                result = safe_parse_json(content)
            
            if not result:
                # 重试都失败，根据关键词判断意图选择 fallback
                operation_keywords = ["发放", "退款", "核销", "入库", "出库", "通知", "回复", "重试", "拒绝", "批准", "查", "查询", "搜索"]
                is_operation = any(kw in task for kw in operation_keywords)
                
                if is_operation:
                    print(f"[Router] JSON 解析失败（重试{retry_count}次），检测到操作类请求，fallback 到 TOOL")
                    return {
                        "mode": "single",
                        "agent": AgentType.TOOL,
                        "reasoning": f"JSON 解析失败（重试{retry_count}次），检测到操作类关键词，fallback 到 TOOL",
                        "understanding": f"用户想要{task}",
                        "analysis": "",
                        "plan": [{"step": 1, "action": task, "tool": "tool", "is_critical": True}],
                        "complexity": "simple"
                    }
                else:
                    print(f"[Router] JSON 解析失败（重试{retry_count}次），fallback 到 RAG")
                    return {
                        "mode": "single",
                        "agent": AgentType.RAG,
                        "reasoning": f"JSON 解析失败（重试{retry_count}次），默认使用 RAG",
                        "understanding": f"用户想要{task}",
                        "analysis": "",
                        "plan": [{"step": 1, "action": task, "tool": "知识检索", "is_critical": True}],
                        "complexity": "simple"
                    }
            
            # 知识性问题直接使用 RAG，不拆分任务
            if result.get("is_knowledge_question"):
                result["mode"] = "single"
                result["agent"] = AgentType.RAG
            
            # 验证结果
            if result.get("mode") not in ["single", "multi"]:
                result["mode"] = "single"
            
            if result.get("mode") == "single" and result.get("agent") not in [AgentType.RAG, AgentType.NL2SQL, AgentType.TOOL, AgentType.VISION]:
                result["agent"] = AgentType.TOOL
            
            # 补充默认值
            if "understanding" not in result:
                result["understanding"] = f"用户想要{task}"
            if "analysis" not in result:
                result["analysis"] = ""
            if "plan" not in result:
                result["plan"] = [{"step": 1, "action": task, "tool": "知识检索", "is_critical": True}]
            if "complexity" not in result:
                result["complexity"] = "simple"
            
            # 保存到缓存
            if len(_plan_cache) >= _cache_max_size:
                _plan_cache.clear()
            _plan_cache[cache_key] = result
            
            return result
        except Exception as e:
            print(f"[Router] 路由判断失败: {str(e)}")
            operation_keywords = ["发放", "退款", "核销", "入库", "出库", "通知", "回复", "重试", "拒绝", "批准", "查", "查询", "搜索"]
            is_operation = any(kw in task for kw in operation_keywords)
            
            if is_operation:
                print(f"[Router] 路由判断失败，检测到操作类请求，fallback 到 TOOL")
                return {
                    "mode": "single",
                    "agent": AgentType.TOOL,
                    "reasoning": f"路由判断失败，检测到操作类关键词，fallback 到 TOOL: {str(e)}",
                    "understanding": f"用户想要{task}",
                    "analysis": "",
                    "plan": [{"step": 1, "action": task, "tool": "tool", "is_critical": True}],
                    "complexity": "simple"
                }
            else:
                print(f"[Router] 路由判断失败，fallback 到 RAG")
                return {
                    "mode": "single",
                    "agent": AgentType.RAG,
                    "reasoning": f"路由判断失败，默认使用 RAG: {str(e)}",
                    "understanding": f"用户想要{task}",
                    "analysis": "",
                    "plan": [{"step": 1, "action": task, "tool": "知识检索", "is_critical": True}],
                    "complexity": "simple"
                }
        """
        判断任务路由
        
        Args:
            task: 用户任务
            has_image: 是否包含图像
            shop_context: 店铺上下文信息（行业、套餐等）
        
        Returns:
            路由结果
            {
                "mode": "single" | "multi",
                "agent": "rag" | "nl2sql" | "tool" | "vision",  # single 模式
                "reasoning": "判断原因"
            }
        """
        # 如果有图像，直接使用 Vision Agent
        if has_image:
            return {
                "mode": "single",
                "agent": AgentType.VISION,
                "reasoning": "包含图像，使用 Vision Agent 处理"
            }
        
        # 检查缓存
        cache_key = _get_cache_key(task, shop_context)
        if cache_key in _plan_cache:
            print(f"[Router] 命中计划缓存: {cache_key}")
            return _plan_cache[cache_key]
        
        try:
            # 使用 LLM 判断任务复杂度
            from langchain_core.messages import HumanMessage
            
            prompt = COMPLEXITY_PROMPT.format(task=task)
            
            # 添加店铺上下文和历史上下文
            if shop_context:
                prompt += f"\n\n## 上下文信息\n{shop_context}"
            
            # 添加明确指令：如何使用历史上下文
            if shop_context and "历史对话" in shop_context:
                prompt += """

## 重要：处理模糊指代和重试指令

当用户的问题是模糊指代（如"重试上面这个问题"、"再试一次"、"那个呢"）时：
1. 先查看【上下文信息】中的历史对话
2. 找到用户上一个具体的问题
3. 将当前问题理解为那个具体问题

示例：
- 历史对话：用户问"今天营业额多少"，助手回答"¥2,580"
- 当前问题："重试上面这个问题"
- 正确理解：用户想要重新查询"今天营业额多少"
- 路由：single + nl2sql（使用原始问题，而不是"重试"这个指令）

- 历史对话：用户问"今天天气怎么样"，助手追问"请问您想了解哪个地方？"
- 当前问题："嘉善"
- 正确理解：用户想查询"嘉善天气"
- 路由：single + rag
"""
            
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            # 解析响应（处理 markdown 代码块）
            content = response.content.strip()
            
            # 提取 JSON
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()
            
            result = safe_parse_json(content)
            
            # JSON 解析失败时重试
            max_retries = 2
            retry_count = 0
            while not result and retry_count < max_retries:
                retry_count += 1
                print(f"[Router] JSON 解析失败，重试 {retry_count}/{max_retries}")
                # 加强 prompt，要求返回严格 JSON
                retry_prompt = prompt + "\n\n【重要】你上次返回的内容不是有效的 JSON。请严格只返回一个 JSON 对象，不要包含任何其他文字。"
                response = await self.llm.ainvoke([HumanMessage(content=retry_prompt)])
                content = response.content.strip()
                
                # 提取 JSON
                if "```json" in content:
                    start = content.find("```json") + 7
                    end = content.find("```", start)
                    content = content[start:end].strip()
                elif "```" in content:
                    start = content.find("```") + 3
                    end = content.find("```", start)
                    content = content[start:end].strip()
                
                result = safe_parse_json(content)
            
            if not result:
                # 重试都失败，根据关键词判断意图选择 fallback
                operation_keywords = ["发放", "退款", "核销", "入库", "出库", "通知", "回复", "重试", "拒绝", "批准", "查", "查询", "搜索"]
                is_operation = any(kw in task for kw in operation_keywords)
                
                if is_operation:
                    print(f"[Router] JSON 解析失败（重试{retry_count}次），检测到操作类请求，fallback 到 TOOL")
                    return {
                        "mode": "single",
                        "agent": AgentType.TOOL,
                        "reasoning": f"JSON 解析失败（重试{retry_count}次），检测到操作类关键词，fallback 到 TOOL",
                        "understanding": f"用户想要{task}",
                        "analysis": "",
                        "plan": [{"step": 1, "action": task, "tool": "tool", "is_critical": True}],
                        "complexity": "simple"
                    }
                else:
                    print(f"[Router] JSON 解析失败（重试{retry_count}次），fallback 到 RAG")
                    return {
                        "mode": "single",
                        "agent": AgentType.RAG,
                        "reasoning": f"JSON 解析失败（重试{retry_count}次），默认使用 RAG",
                        "understanding": f"用户想要{task}",
                        "analysis": "",
                        "plan": [{"step": 1, "action": task, "tool": "知识检索", "is_critical": True}],
                        "complexity": "simple"
                    }
            
            # 知识性问题直接使用 RAG，不拆分任务
            if result.get("is_knowledge_question"):
                result["mode"] = "single"
                result["agent"] = AgentType.RAG
            
            # 验证结果
            if result.get("mode") not in ["single", "multi"]:
                result["mode"] = "single"
            
            if result.get("mode") == "single" and result.get("agent") not in [AgentType.RAG, AgentType.NL2SQL, AgentType.TOOL, AgentType.VISION]:
                result["agent"] = AgentType.TOOL
            
            # 补充默认值（如果 LLM 没有返回这些字段）
            if "understanding" not in result:
                result["understanding"] = f"用户想要{task}"
            if "analysis" not in result:
                result["analysis"] = ""
            if "plan" not in result:
                result["plan"] = [{"step": 1, "action": task, "tool": "知识检索", "is_critical": True}]
            if "complexity" not in result:
                result["complexity"] = "simple"
            
            # 保存到缓存
            if len(_plan_cache) >= _cache_max_size:
                # 清空缓存（简单策略）
                _plan_cache.clear()
            _plan_cache[cache_key] = result
            
            return result
        except Exception as e:
            print(f"[Router] 路由判断失败: {str(e)}")
            # 根据关键词判断意图选择 fallback
            operation_keywords = ["发放", "退款", "核销", "入库", "出库", "通知", "回复", "重试", "拒绝", "批准", "查", "查询", "搜索"]
            is_operation = any(kw in task for kw in operation_keywords)
            
            if is_operation:
                print(f"[Router] 路由判断失败，检测到操作类请求，fallback 到 TOOL")
                return {
                    "mode": "single",
                    "agent": AgentType.TOOL,
                    "reasoning": f"路由判断失败，检测到操作类关键词，fallback 到 TOOL: {str(e)}",
                    "understanding": f"用户想要{task}",
                    "analysis": "",
                    "plan": [{"step": 1, "action": task, "tool": "tool", "is_critical": True}],
                    "complexity": "simple"
                }
            else:
                print(f"[Router] 路由判断失败，fallback 到 RAG")
                return {
                    "mode": "single",
                    "agent": AgentType.RAG,
                    "reasoning": f"路由判断失败，默认使用 RAG: {str(e)}",
                    "understanding": f"用户想要{task}",
                    "analysis": "",
                    "plan": [{"step": 1, "action": task, "tool": "知识检索", "is_critical": True}],
                    "complexity": "simple"
                }
    
    async def _generate_plan(self, task: str, shop_context: str = "") -> dict:
        """
        生成执行计划
        
        Args:
            task: 用户问题
            shop_context: 店铺上下文信息
        
        Returns:
            计划字典
        """
        try:
            from langchain_core.messages import HumanMessage
            
            prompt = PLAN_GENERATION_PROMPT.format(task=task)
            
            # 添加店铺上下文
            if shop_context:
                prompt += f"\n\n## 店铺信息\n{shop_context}"
            
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            # 解析 JSON
            content = response.content.strip()
            result = safe_parse_json(content)
            if not result:
                return {
                    "understanding": f"用户想要{task}",
                    "analysis": "",
                    "plan": [{"step": 1, "action": task, "tool": "知识检索", "is_critical": True}],
                    "expected_result": "回答用户问题",
                    "complexity": "simple"
                }
            return result
        except Exception as e:
            print(f"[Router] 计划生成失败: {str(e)}")
            # 返回默认计划
            return {
                "understanding": f"用户想要{task}",
                "analysis": "",
                "plan": [{"step": 1, "action": task, "tool": "知识检索", "purpose": "处理用户问题", "expected": "获得答案", "is_critical": True, "depends_on": []}],
                "expected_result": "回答用户问题",
                "complexity": "simple"
            }
    
    async def split_task(self, task: str) -> List[SubTask]:
        """
        拆分复杂任务为多个子任务（支持依赖关系）
        
        Args:
            task: 用户任务
        
        Returns:
            子任务列表
        """
        try:
            # 使用 LLM 拆分任务
            from langchain_core.messages import HumanMessage
            
            prompt = TASK_SPLIT_PROMPT.format(task=task)
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            # 解析响应（处理 markdown 代码块）
            content = response.content.strip()
            
            sub_tasks_data = safe_parse_json(content)
            if not sub_tasks_data or not isinstance(sub_tasks_data, list):
                print(f"[TaskRouter] JSON 解析失败，返回默认子任务")
                return [SubTask(
                    id=1,
                    task=task,
                    agent=AgentType.TOOL,
                    description="原始任务",
                    depends_on=[],
                )]
            
            # 转换为 SubTask 对象
            sub_tasks = []
            for sub_task_data in sub_tasks_data:
                sub_task = SubTask(
                    id=sub_task_data.get("id", len(sub_tasks) + 1),
                    task=sub_task_data.get("task", ""),
                    agent=sub_task_data.get("agent", AgentType.TOOL),
                    tool_name=sub_task_data.get("tool_name", ""),
                    description=sub_task_data.get("description", ""),
                    depends_on=sub_task_data.get("depends_on", []),
                )
                sub_tasks.append(sub_task)
            
            print(f"[TaskRouter] 任务拆分成功: {task} -> {len(sub_tasks)} 个子任务")
            for sub_task in sub_tasks:
                deps = f" (依赖: {sub_task.depends_on})" if sub_task.depends_on else " (无依赖)"
                tool = f" tool={sub_task.tool_name}" if sub_task.tool_name else ""
                print(f"  - 子任务{sub_task.id}: {sub_task.task} [{sub_task.agent}]{tool}{deps}")
            
            return sub_tasks
            
        except Exception as e:
            print(f"[TaskRouter] 任务拆分失败: {str(e)}")
            # 拆分失败，返回单个子任务
            return [SubTask(
                id=1,
                task=task,
                agent=AgentType.TOOL,
                description="原始任务",
                depends_on=[],
            )]
    
    async def create_plan(self, task: str, has_image: bool = False, shop_context: str = "", previous_rounds: list = None) -> TaskPlan:
        """
        创建任务执行计划
        
        优先级：
        1. 匹配预设 Skill（最高成功率）
        2. 规则判断任务类型
        
        Args:
            task: 用户任务（重试时包含上轮执行上下文）
            has_image: 是否包含图像
            shop_context: 店铺上下文（包含历史对话）
            previous_rounds: 上轮执行记录（重试时传入，用于智能跳过已完成的子任务）
        
        Returns:
            任务执行计划
        """
        # 1. 尝试匹配预设 Skill
        skill_manager = get_skill_manager()
        match_result = skill_manager.match(task, min_score=0.5)
        
        if match_result:
            skill, score = match_result
            print(f"[Router] 匹配到预设 Skill: {skill.name} (分数: {score:.2f})")
            
            # 将 Skill 步骤转换为 SubTask
            sub_tasks = []
            for step in skill.steps:
                sub_task = SubTask(
                    id=step.step,
                    task=step.task,
                    agent=step.agent,
                    description=step.description,
                    query=step.query,
                    depends_on=step.depends_on,
                )
                
                # 如果有上轮执行记录，将成功的结果挂到子任务上
                if previous_rounds:
                    last_round = previous_rounds[-1]
                    prev_data = last_round.get("sub_tasks", {}).get(step.step)
                    if prev_data and prev_data.get("success") and prev_data.get("result"):
                        sub_task.result = AgentResult(
                            agent=step.agent,
                            result=prev_data["result"],
                            confidence=0.9,
                            success=True,
                        )
                        print(f"[Router] 子任务 {step.step} 复用上轮结果")
                
                sub_tasks.append(sub_task)
            
            # 提取所有需要的 Agent 类型
            agents = list(set(step.agent for step in skill.steps))
            
            # 判断是否需要串行执行（有依赖关系）
            has_dependencies = any(step.depends_on for step in skill.steps)
            
            return TaskPlan(
                task=task,
                complexity=TaskComplexity.COMPLEX if len(sub_tasks) > 1 else TaskComplexity.SIMPLE,
                agents=agents,
                parallel=not has_dependencies,
                reasoning=f"匹配预设 Skill: {skill.name} (置信度: {score:.2f})",
                sub_tasks=sub_tasks,
                from_skill=True,
            )
        
        # 2. 使用规则判断任务类型
        route_result = await self.route(task, has_image, shop_context)
        
        if route_result["mode"] == "single":
            # 简单任务，单个 Agent
            return TaskPlan(
                task=task,
                complexity=TaskComplexity.SIMPLE,
                agents=[route_result["agent"]],
                parallel=False,
                reasoning=route_result["reasoning"]
            )
        else:
            # 复杂任务，使用 LLM 拆分
            sub_tasks = await self.split_task(task)
            
            # 提取所有需要的 Agent 类型
            agents = list(set(sub_task.agent for sub_task in sub_tasks))
            
            # 判断是否需要串行执行（有依赖关系）
            has_dependencies = any(sub_task.depends_on for sub_task in sub_tasks)
            
            return TaskPlan(
                task=task,
                complexity=TaskComplexity.COMPLEX,
                agents=agents,
                parallel=not has_dependencies,
                reasoning=route_result["reasoning"],
                sub_tasks=sub_tasks,
            )
    
    def _determine_agents(self, task: str) -> list:
        """根据任务内容确定需要的 Agent"""
        agents = []
        
        # 关键词映射
        keyword_agent_map = {
            "营收": AgentType.NL2SQL,
            "营业额": AgentType.NL2SQL,
            "收入": AgentType.NL2SQL,
            "业绩": AgentType.NL2SQL,
            "顾客": AgentType.TOOL,
            "会员": AgentType.TOOL,
            "库存": AgentType.TOOL,
            "物料": AgentType.TOOL,
            "套餐": AgentType.RAG,
            "价格": AgentType.RAG,
            "营业时间": AgentType.RAG,
            "规则": AgentType.RAG,
            "员工": AgentType.TOOL,
            "排班": AgentType.TOOL,
            "考勤": AgentType.TOOL,
            "优惠券": AgentType.TOOL,
            "评价": AgentType.TOOL,
            "分析": AgentType.NL2SQL,
            "报表": AgentType.NL2SQL,
        }
        
        for keyword, agent_type in keyword_agent_map.items():
            if keyword in task and agent_type not in agents:
                agents.append(agent_type)
        
        # 如果没有匹配到，默认使用 Tool Agent
        if not agents:
            agents.append(AgentType.TOOL)
        
        return agents


# 全局实例
_task_router = None


def get_task_router() -> TaskRouter:
    """获取智能路由单例"""
    global _task_router
    if _task_router is None:
        _task_router = TaskRouter()
    return _task_router
