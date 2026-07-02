"""
智能路由模块（优化版）
使用 LLM 一次性完成问题理解和任务分配
"""

import json
import hashlib
import time
from typing import Dict, Any, Optional, List
from app.llm import get_chat_llm
from app.multi_agent.protocol import TaskPlan, TaskComplexity, AgentType, SubTask, AgentResult
from app.utils.json_parser import safe_parse_json
from app.skills.manager import get_skill_manager
from cachetools import TTLCache


# 计划缓存（内存缓存，相似问题复用，5分钟自动过期）
_plan_cache = TTLCache(maxsize=100, ttl=300)


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
- refund_approve: 审批退款（批准）。支持单条和批量，批量时工具自动处理多个退款ID
- refund_reject: 审批退款（拒绝）。支持单条和批量，批量时工具自动处理多个退款ID
- game_session_checkin: 核销入座
- game_session_finish: 结束游玩
- material_inbound: 物料入库
- material_outbound: 物料出库
- grant_coupon: 发放优惠券
- reply_feedback: 回复评价
- send_notification: 发送通知

**使用规则**：
- 用户说"批准退款" → tool: refund_approve（支持单条和批量）
- 用户说"拒绝退款" → tool: refund_reject（支持单条和批量）
- 用户说"所有/全部/批量" + 退款操作 → tool: refund_approve 或 refund_reject，工具自动查询并弹出批量确认框
- 用户说"核销" → tool: game_session_checkin
- 用户说"入库/出库" → tool: material_inbound / material_outbound
- 用户说"发放优惠券" → tool: grant_coupon
- 用户说"回复评价" → tool: reply_feedback
- 用户说"发通知" → tool: send_notification
- 禁止生成如"上下文理解"、"数据查询"、"工具调用"等描述性名称

## 判断规则（按优先级）

### 0. tool 和 nl2sql 的区别（重要！）
- **tool**: 直接调用预定义工具函数，用于执行操作（退款、发放优惠券、核销等）
  - "批准退款" → tool: refund_approve（支持单条和批量）
  - "拒绝退款" → tool: refund_reject（支持单条和批量）
  - "拒绝所有退款" → tool: refund_reject（工具自动查询并弹出批量确认框）
  - "批准所有退款" → tool: refund_approve（工具自动查询并弹出批量确认框）
  - "发放优惠券" → tool: grant_coupon
- **nl2sql**: 需要 LLM 生成 SQL 查询数据库，用于所有数据查询
  - "查询退款记录" → nl2sql
  - "查询已完成退款" → nl2sql
  - "查询退款总金额" → nl2sql
  - "查询顾客张三" → nl2sql
  - "查询库存" → nl2sql
  - "哪些物料库存低于10个" → nl2sql
  - "本月营业额趋势" → nl2sql
  - "哪些套餐卖得最好" → nl2sql

### 1. 上下文相关问题 → single + llm
用户在追问之前对话中的内容，或询问术语含义：
- "这个是什么意思？"
- "你输出的这个是支出吗？"
- "为什么是这个数字？"
- "能解释一下吗？"

### 1b. 文件解读问题 → single + llm
用户上传了文件并要求解读/解释/总结/输出文件内容。文件内容已在对话上下文中，直接用 llm 读取上下文并回答，不需要检索知识库：
- "解读一下该文件" → llm
- "这个文件里有什么？" → llm
- "总结一下文件内容" → llm
- "输出一下文件内容" → llm
- "分析一下这个表格" → llm
- "帮我看看这个文档" → llm

**重要**：文件解读 ≠ 知识问答。不要路由到 rag，rag 是去知识库检索相关文档，而文件解读是读取已提供的文件内容。

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
- "套餐多少钱？" → rag（查知识库，不是查数据库）
- "本月卖了多少套餐？" → nl2sql（查数据库聚合数据）
- "退款政策是什么？" → rag（查知识库）
- "有哪些退款申请？" → nl2sql（查数据库实时数据）

### 3. 数据查询问题 → single + nl2sql
需要查询当前店铺的具体数据，统一使用 nl2sql：
- 查询类："今天营业额多少？"、"有多少顾客？"
- 统计类："本月销售排名？"、"库存还有多少？"
- 筛选类："查询已完成退款"、"查询处理中的退款"
- 聚合类："退款总金额"、"本月营业额"
- 省略句：结合历史对话理解（如"本月呢？" → "本月的收入"）

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

### 7. 多操作识别（重要！）
当用户指令包含多个操作时，必须使用 multi 模式拆分：
- "同意X退款，拒绝Y的" → multi: [refund_approve(X), refund_reject(Y)]
- "给张三发通知，给李四发优惠券" → multi: [send_notification, grant_coupon]
- "入库100个石膏，出库50个颜料" → multi: [material_inbound, material_outbound]
- "查询营业额，然后批准退款" → multi: [nl2sql查询, refund_approve]

判断方法：如果用户指令中包含"和"、"同时"、"然后"、"，"连接的多个操作，使用 multi 模式。

### 8. 操作工具使用规则（重要！）
当用户要求执行操作时，必须使用对应的操作工具，禁止使用 LLM Agent：
- "同意退款"、"批准退款" → tool: refund_approve
- "拒绝退款" → tool: refund_reject
- "发放优惠券" → tool: grant_coupon
- "核销"、"入座" → tool: game_session_checkin
- "结束游玩" → tool: game_session_finish
- "入库" → tool: material_inbound
- "出库" → tool: material_outbound
- "回复评价" → tool: reply_feedback
- "发通知" → tool: send_notification

注意：操作工具会自动处理参数解析（Agent Loop），不需要提前确认参数是否齐全。
即使用户只提供了顾客姓名（如"同意林志玲退款"），Agent Loop 会从上下文中解析出退款ID。

### 9. 上下文使用规则（重要！）
- 如果用户引用了之前的查询结果（如"上面的退款"、"林志玲的"），从对话历史中获取信息
- 不要因为"缺少参数"就拒绝执行，Agent Loop 会从上下文中解析参数
- 如果对话历史中有相关数据，直接执行操作，不要要求用户提供更多信息
- 示例：用户之前查过退款列表，现在说"同意林志玲退款"，直接执行，不要说"未找到记录"

### 10. 工具选择优先级
1. 数据查询 → nl2sql（统一使用，不再区分 query 工具）
2. 操作类请求 → 对应的操作工具（refund_approve 等）
3. 知识问答 → rag
4. 分析总结 → llm
5. 多个操作 → multi 模式，每个操作分配对应的工具

禁止：操作类请求使用 LLM Agent 或 rag

## plan.tool 填写规则（必须严格遵守）
plan 中每个步骤的 tool 字段决定了执行器如何调度，填写错误会导致执行失败：
- agent=rag 时，plan.tool 必须填 "rag"
- agent=nl2sql 时，plan.tool 必须填 "nl2sql"
- agent=llm 时，plan.tool 必须填 "llm"
- agent=tool 时，plan.tool 必须填 TOOL_MAP 中的具体名称（如 refund_approve, grant_coupon）
- 禁止编造不存在的 tool 名（如 rag_knowledge_retrieval、nl2sql_query、数据查询 等）

## 输出格式

请返回严格的 JSON 格式：

{{
    "mode": "single 或 multi",
    "agent": "rag/nl2sql/tool/llm/vision"（single 模式时）,
    "tool_name": "具体的tool名称"（仅当agent=tool时填写，必须是上面列出的名称）,
    "reasoning": "判断原因",
    "is_knowledge_question": true/false,
    "understanding": "用一句自然语言描述用户的真实意图和期望（如：用户希望解读上传的顾客名单，了解文件包含哪些数据）",
    "analysis": "分析问题的核心需求",
    "plan": [
        {{
            "step": 1,
            "action": "描述该步骤要做什么、怎么做、期望输出什么（如：检索知识库中的退款政策文档，向用户解释退款条件和流程）",
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

## 重要：输出格式要求（必须严格遵守，否则系统无法处理）

### JSON格式规范：
1. **只返回JSON**：你必须只返回一个完整的 JSON 对象，不要包含任何其他文字、解释或 markdown 代码块标记（不要用 ```json ```）
2. **有效JSON格式**：JSON 必须是有效的格式，所有字符串必须用双引号（不要用单引号）
3. **不要添加前缀**：不要在 JSON 前添加"以下是JSON："、"结果："等文字
4. **不要添加后缀**：不要在 JSON 后添加解释说明
5. **完整闭合**：确保所有括号、引号都正确闭合
6. **无换行符**：JSON 内容不要包含实际的换行符（可以用 \n 转义）
7. **禁止返回裸字符串**：不要返回单独的字符串如 "mode"、"single" 或 "rag"，必须返回包含 mode/agent/plan 等字段的完整 JSON 对象 {{...}}

### 必须包含的字段：
- "mode": 必须是 "single" 或 "multi"
- "agent": 必须是 "rag"、"nl2sql"、"tool"、"llm"、"vision" 之一
- "reasoning": 字符串，说明判断原因
- "understanding": 字符串，说明用户意图
- "analysis": 字符串，说明分析结果
- "plan": 数组，每个元素包含 step、action、tool、is_critical
  - **重要**：如果用户上传了文件（消息中包含 `<document>` 标签），必须在对应步骤的 action 中显式列出文件内的关键数据项（姓名、手机号、ID等），禁止使用"Excel中的顾客"等模糊描述。格式：action="查询以下顾客的购买记录：张三(138xxxx)、李四(139xxxx)"
- "complexity": 必须是 "simple"、"medium"、"complex" 之一

### 常见错误示例（禁止）：
❌ 错误1：添加了markdown标记
```json
{{"mode": "single", ...}}
```

❌ 错误2：添加了前缀文字
以下是JSON：{{"mode": "single", ...}}

❌ 错误3：使用了单引号
{{'mode': 'single', ...}}

❌ 错误4：JSON不完整
{{"mode": "single", "agent": "nl2sql"

❌ 错误5：包含实际换行符
{{"mode": "single",
"agent": "nl2sql"}}

### 正确示例（必须这样写）：
✅ {{"mode": "single", "agent": "nl2sql", "reasoning": "用户查询营业额", "understanding": "用户想查询本月营业额", "analysis": "查询purchases表", "plan": [{{"step": 1, "action": "查询本月营业额", "tool": "nl2sql", "is_critical": true}}], "complexity": "simple"}}

### 验证方法：
在返回前，检查你的输出：
1. 是否以 {{ 开头，以 }} 结尾？
2. 是否有 ```json ``` 标记？（不要有）
3. 所有字符串是否用双引号？
4. 所有括号是否正确闭合？
5. 是否包含任何非JSON文字？（不要有）

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
- refund_approve: 批准退款（支持单条和批量，批量时工具自动查询待处理退款并弹出批量确认框）
- refund_reject: 拒绝退款（支持单条和批量，批量时工具自动查询待处理退款并弹出批量确认框）
- game_session_checkin: 核销入座（需要 customer_id, customer_session_id）
- game_session_finish: 结束游玩（需要 game_session_id）
- material_inbound: 物料入库（需要 material_id, quantity）
- material_outbound: 物料出库（需要 material_id, quantity）
- grant_coupon: 发放优惠券（需要 coupon_id, customer_ids）
- reply_feedback: 回复评价（需要 feedback_id, reply_content）
- send_notification: 发送通知（需要 recipient_ids, recipient_type, title, content）

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
1. **每个操作必须是独立的子任务**，不要将多个操作合并
2. 查询类子任务必须放在操作类子任务之前
3. 操作子任务必须指定 tool_name
4. 子任务之间有依赖关系时，必须指定 depends_on
5. 保持原始任务的语义，不要遗漏信息

## 示例

### 示例1：退款审批（多个操作）
任务："黄晓明的审核通过，赵丽颖的审核拒绝"
[
    {{"id": 1, "task": "查询黄晓明和赵丽颖的待处理退款信息", "agent": "nl2sql", "tool_name": "", "description": "获取退款记录ID", "depends_on": []}},
    {{"id": 2, "task": "批准黄晓明的退款", "agent": "tool", "tool_name": "refund_approve", "description": "调用退款批准工具", "depends_on": [1]}},
    {{"id": 3, "task": "拒绝赵丽颖的退款", "agent": "tool", "tool_name": "refund_reject", "description": "调用退款拒绝工具", "depends_on": [1]}}
]

### 示例2：发放优惠券
任务："给所有顾客发满100减15优惠券"
[
    {{"id": 1, "task": "查询满100减15优惠券的ID", "agent": "nl2sql", "tool_name": "", "description": "获取优惠券ID", "depends_on": []}},
    {{"id": 2, "task": "查询所有顾客ID", "agent": "nl2sql", "tool_name": "", "description": "获取顾客ID列表", "depends_on": []}},
    {{"id": 3, "task": "发放优惠券给所有顾客", "agent": "tool", "tool_name": "grant_coupon", "description": "调用发放优惠券工具", "depends_on": [1, 2]}}
]

### 示例3：核销入座
任务："帮张三核销"
[
    {{"id": 1, "task": "查询张三的进行中场次信息", "agent": "nl2sql", "tool_name": "", "description": "获取customer_id和customer_session_id", "depends_on": []}},
    {{"id": 2, "task": "核销张三入座", "agent": "tool", "tool_name": "game_session_checkin", "description": "调用核销入座工具", "depends_on": [1]}}
]

### 示例4：结束游玩
任务："结束张三的游玩"
[
    {{"id": 1, "task": "查询张三的进行中场次ID", "agent": "nl2sql", "tool_name": "", "description": "获取game_session_id", "depends_on": []}},
    {{"id": 2, "task": "结束张三的游玩", "agent": "tool", "tool_name": "game_session_finish", "description": "调用结束游玩工具", "depends_on": [1]}}
]

### 示例5：物料入库
任务："入库100个石膏娃娃"
[
    {{"id": 1, "task": "查询石膏娃娃的物料ID", "agent": "nl2sql", "tool_name": "", "description": "获取material_id", "depends_on": []}},
    {{"id": 2, "task": "入库100个石膏娃娃", "agent": "tool", "tool_name": "material_inbound", "description": "调用物料入库工具", "depends_on": [1]}}
]

### 示例6：物料出库
任务："出库50个颜料"
[
    {{"id": 1, "task": "查询颜料的物料ID", "agent": "nl2sql", "tool_name": "", "description": "获取material_id", "depends_on": []}},
    {{"id": 2, "task": "出库50个颜料", "agent": "tool", "tool_name": "material_outbound", "description": "调用物料出库工具", "depends_on": [1]}}
]

### 示例7：回复评价
任务："回复张三的评价"
[
    {{"id": 1, "task": "查询张三的待回复评价", "agent": "nl2sql", "tool_name": "", "description": "获取feedback_id", "depends_on": []}},
    {{"id": 2, "task": "回复张三的评价", "agent": "tool", "tool_name": "reply_feedback", "description": "调用回复评价工具", "depends_on": [1]}}
]

### 示例8：发送通知
任务："给所有顾客发通知说明天放假"
[
    {{"id": 1, "task": "查询所有顾客ID", "agent": "nl2sql", "tool_name": "", "description": "获取顾客ID列表", "depends_on": []}},
    {{"id": 2, "task": "发送放假通知给所有顾客", "agent": "tool", "tool_name": "send_notification", "description": "调用发送通知工具", "depends_on": [1]}}
]

### 示例9：混合任务（查询+操作）
任务："查询本月营业额，然后批准黄晓明的退款"
[
    {{"id": 1, "task": "查询本月营业额数据", "agent": "nl2sql", "tool_name": "", "description": "查询本月的营业额", "depends_on": []}},
    {{"id": 2, "task": "查询黄晓明的待处理退款ID", "agent": "nl2sql", "tool_name": "", "description": "获取退款记录ID", "depends_on": []}},
    {{"id": 3, "task": "批准黄晓明的退款", "agent": "tool", "tool_name": "refund_approve", "description": "调用退款批准工具", "depends_on": [2]}}
]

### 示例10：经营分析
任务："分析本月经营情况"
[
    {{"id": 1, "task": "查询本月营收数据", "agent": "nl2sql", "tool_name": "", "description": "查询本月营业额、订单数、热销套餐", "depends_on": []}},
    {{"id": 2, "task": "查询本月顾客数据", "agent": "nl2sql", "tool_name": "", "description": "查询本月新顾客数、活跃顾客数", "depends_on": []}},
    {{"id": 3, "task": "查询本月支出数据", "agent": "nl2sql", "tool_name": "", "description": "查询本月各类支出", "depends_on": []}},
    {{"id": 4, "task": "汇总分析并给出建议", "agent": "llm", "tool_name": "", "description": "基于以上数据进行分析并给出建议", "depends_on": [1, 2, 3]}}
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

            prompt = f"""你是店铺智能助手的路由判断模块。你的职责是帮助店长管理店铺，包括查询数据（营业额、顾客、库存）、执行操作（退款审批、优惠券发放、核销）、回答问题。

判断用户输入的性质，决定如何处理。

## 用户输入
"{question}"
{history_section}
{shop_section}

## 高优先级 Skills
以下是系统预设的高优先级 Skills。Skill 是**预定义的多步骤综合分析工具**，适合需要查询多个维度数据并汇总的复杂问题。
**单一指标查询（如只问一个数字或一个指标）不应匹配 Skill，应直接走 nl2sql。**

【匹配原则】
- ✅ 应匹配：问题包含"分析""情况""综合""总结"等综合分析关键词，需要多方面数据
- ❌ 不应匹配：问题只是查询某个具体单一指标（如"今天营业额多少""本月营收多少""退了多少款"）

【各 Skill 详细说明】

1. **今日经营概况**（id: daily_business_summary）
   - 用途：综合展示今天的经营全貌，包括营业额、核销数、新顾客、热销套餐、库存预警
   - 适用场景：用户想"看看今天怎么样""了解一下今天的情况"
   - 排除条件：只问单一指标（"今天营业额多少""今天核销了多少单"）→ 走 nl2sql
   - 关键词：今天、今日、日报、当天、今日概况、今日经营

2. **本月经营情况分析**（id: monthly_business_analysis）
   - 用途：综合分析本月经营状况，包括营收、顾客、支出、退款、热销套餐等多维度数据
   - 适用场景：用户想"分析一下本月情况""本月经营怎么样""做个月报"
   - 排除条件：只问本月某个单一指标（"本月营收多少""本月利润多少""这个月来了多少顾客"）→ 走 nl2sql
   - 关键词：本月、经营、情况、分析、月度、这个月、月报

3. **退款分析**（id: refund_analysis）
   - 用途：综合分析退款情况，包括状态分布、原因分布、趋势
   - 适用场景：用户想"分析退款情况""看看退款原因""退款统计"
   - 排除条件：只查退款金额或笔数（"退了多少款""有几笔退款"）→ 走 nl2sql
   - 关键词：退款、退货、退款率、退款原因、退款分析、退款统计

4. **顾客消费分析**（id: customer_consumption_analysis）
   - 用途：分析顾客消费行为，包括消费金额、频次分布、来源渠道
   - 适用场景：用户想"分析顾客消费""会员分析""顾客画像"
   - 排除条件：只查顾客数量或信息（"有多少顾客""今天来了几个新顾客"）→ 走 nl2sql
   - 关键词：顾客、消费、会员、客户

5. **员工绩效**（id: staff_performance）
   - 用途：分析员工绩效表现，包括核销数排行、考勤统计
   - 适用场景：用户想"看看员工表现""业绩排行""员工绩效分析"
   - 排除条件：只查员工信息或单个员工数据（"有哪些员工""张三今天核销了多少"）→ 走 nl2sql
   - 关键词：员工、绩效、业绩、核销、销售额、排行

6. **月度对比**（id: monthly_comparison）
   - 用途：对比本月和上月的经营数据，包括营收、订单数等
   - 适用场景：用户想"对比这个月和上个月""环比增长了多少"
   - 排除条件：只查某个月的数据（"上个月营收多少"）→ 走 nl2sql
   - 关键词：对比、比较、本月、上月、环比、增长

7. **库存查询**（id: inventory_query）
   - 用途：查询整体库存状态和预警信息
   - 适用场景：用户想"看看库存情况""有哪些物料缺货"
   - 排除条件：只查某个具体物料的库存（"洗衣液还有多少"）→ 走 nl2sql
   - 关键词：库存、物料、货物、存货、缺货

8. **收支查询**（id: revenue_expense_query）
   - 用途：同时查询收入与支出数据
   - 适用场景：用户想同时看"收入和支出情况""本月赚了多少花了多少"
   - 排除条件：只查收入或只查支出（"这个月支出多少""收入多少"）→ 走 nl2sql
   - 关键词：收入、支出、收支、利润、盈亏、赚、花

## 判断任务

请判断以下问题，并返回所有判断结果：

### 1. 输入是否有效？

有效的输入：有意义的问题、请求、操作指令、问候
无效的输入：无意义字符、测试输入、不完整输入、纯表情

### 2. 是否匹配到高优先级 Skill？

Skill 是**多步骤综合分析工具**，不是普通的查询接口。以下原则决定是否匹配：

匹配原则：
- ✅ 匹配：问题意图为"全面分析/全方位了解"，涉及多个维度
- ❌ 不匹配：问题只涉及一个具体指标或一个具体数据，应走 nl2sql

判断方法：
1. 看问题的**意图**：是要"全面分析"还是只要"一个数字"？
2. 看问题的**范围**：涉及多个维度（营收+顾客+支出）还是单一维度？
3. 看问题的**措辞**：包含"分析""情况""总结""怎么样"等综合词？还是只问了数据？
- 如果匹配到，返回 matched_skill 字段，包含匹配的 Skill ID
- 如果没有匹配到，matched_skill 返回 null

### 3. 是否是上下文相关问题？

判断方法：用户的问题是否需要结合之前的对话才能理解？

- 是：引用之前的内容（"那林志玲的呢"）、纠正之前的回答（"处理中不就是待处理嘛"）、确认之前的结论
- 否：全新的问题

### 4. 是否需要追问？

判断方法：用户的问题是否有足够的信息来执行？

- 需要追问：缺少关键信息，且对话历史中也没有（如只说"退款"，没说哪个顾客）
- 不需要追问：意图清晰，或可从对话历史推断

### 5. 用户想要什么？

判断用户当前的**真实意图**，从以下三种中选择：

**A. 执行操作**（is_operation=true, need_requery=false）
用户想要执行一个具体的操作（退款、发放优惠券、核销等）

**B. 获取数据**（is_operation=false, need_requery=true）
用户想要查询数据库获取信息，包括：
- 查询新数据："今天营业额多少"
- 验证/核实已有数据："再次确认金额统计是否正确"、"帮我再查一下"
- 获取更新的数据："重新查一下今天的库存"
- 追问数据相关问题："5月份的你为什么不查询？"、"这个数据对吗？"、"为什么退款这么多？"
- 质疑数据准确性："你确定只有2笔？"、"这个金额对吗？"

**C. 对话交流**（is_operation=false, need_requery=false）
用户想要讨论、解释、确认已有信息，不需要查询数据库：
- 纠正/确认："处理中不就是待处理嘛"、"你说的对"
- 闲聊/问候："你好"、"好的"
- 纯文本追问："为什么这么说"（不需要查数据）

### 操作类请求的追问规则（重要）

如果用户的问题是操作类请求，即使缺少参数，也不要追问。操作类请求缺少参数时，路由到对应的工具，让工具的确认弹窗让用户填写。

判断方法：
1. 用户的请求是否包含明确的操作动词？（入库、退款、发放、核销、回复、发送、拒绝、批准、同意）
2. 用户是否指定了操作对象？（洗衣液、张三、优惠券）
3. 如果动词+对象都有 → 意图明确，不需要追问
4. 如果只有动词没有对象 → 可能需要追问
5. 如果动词和对象都没有 → 需要追问

示例：
- "物料库存加入这个洗衣液" → 意图明确（入库洗衣液），不需要追问
- "拒绝退款" → 意图明确（拒绝退款），不需要追问
- "退款" → 意图不明确（哪个顾客？批准还是拒绝？），需要追问
- "帮我处理一下" → 意图完全不明确，需要追问

### 特殊情况：确认性回复

当用户回复"是的"、"对"、"是"、"确认"、"好的"等确认性词语时，需要根据对话历史判断确认的内容：

1. 查看对话历史中助手的上一个问题
2. 判断助手问题的性质：
   - 助手问的是"是否要查询XX数据" → B（获取数据）
   - 助手问的是"是否要执行XX操作" → A（执行操作）
   - 助手问的是文本确认 → C（对话交流）

示例：
- 助手: "请问具体指哪两个的金额？" → 用户: "是的" → B（查询金额）
- 助手: "确定要退款吗？" → 用户: "是的" → A（执行退款）
- 助手: "我理解对了吗？" → 用户: "是的" → C（文本确认）

判断方法：
- 如果用户的问题**需要从数据库获取信息**才能回答 → B
- 如果用户的问题**基于对话历史的文字就能回答** → C
- 如果用户想要**执行一个具体操作** → A
- 如果用户是**确认性回复**，根据助手上一个问题的性质判断

## 路由决策

根据第 5 节的判断：
- A（执行操作）→ 继续路由到工具
- B（获取数据）→ 继续路由到 nl2sql
- C（对话交流）→ 直接返回 LLM Agent

其他优先级：
- is_valid=false → 无效输入，返回提示
- need_clarify=true → 需要追问
- matched_skill != null → 优先使用 Skill 执行

## 输出格式
返回 JSON：
{{"is_valid": true/false, "is_context_question": true/false, "need_clarify": false, "is_operation": true/false, "need_requery": false, "matched_skill": "skill_id 或 null", "reason": "判断原因（简短说明）", "missing_info": "缺少的信息（仅 need_clarify=true 时填写）"}}

【重要】输出格式要求：
1. 只返回一个完整的 JSON 对象
2. 不要包含任何其他文字、解释或 markdown 代码块标记
3. 所有字符串必须用双引号
4. 布尔值必须是 true/false（小写）
5. matched_skill 如果没有匹配到，返回 null（不是字符串"null"）"""
            
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

            prompt = f"""你是店铺智能助手的路由判断模块。你的职责是帮助店长管理店铺，包括查询数据（营业额、顾客、库存）、执行操作（退款审批、优惠券发放、核销）、回答问题。

判断用户输入的性质，决定如何处理。

## 用户输入
"{question}"
{history_section}
{shop_section}

## 高优先级 Skills
以下是系统预设的高优先级 Skills。Skill 是**预定义的多步骤综合分析工具**，适合需要查询多个维度数据并汇总的复杂问题。
**单一指标查询（如只问一个数字或一个指标）不应匹配 Skill，应直接走 nl2sql。**

【匹配原则】
- ✅ 应匹配：问题包含"分析""情况""综合""总结"等综合分析关键词，需要多方面数据
- ❌ 不应匹配：问题只是查询某个具体单一指标（如"今天营业额多少""本月营收多少""退了多少款"）

【各 Skill 详细说明】

1. **今日经营概况**（id: daily_business_summary）
   - 用途：综合展示今天的经营全貌，包括营业额、核销数、新顾客、热销套餐、库存预警
   - 适用场景：用户想"看看今天怎么样""了解一下今天的情况"
   - 排除条件：只问单一指标（"今天营业额多少""今天核销了多少单"）→ 走 nl2sql
   - 关键词：今天、今日、日报、当天、今日概况、今日经营

2. **本月经营情况分析**（id: monthly_business_analysis）
   - 用途：综合分析本月经营状况，包括营收、顾客、支出、退款、热销套餐等多维度数据
   - 适用场景：用户想"分析一下本月情况""本月经营怎么样""做个月报"
   - 排除条件：只问本月某个单一指标（"本月营收多少""本月利润多少""这个月来了多少顾客"）→ 走 nl2sql
   - 关键词：本月、经营、情况、分析、月度、这个月、月报

3. **退款分析**（id: refund_analysis）
   - 用途：综合分析退款情况，包括状态分布、原因分布、趋势
   - 适用场景：用户想"分析退款情况""看看退款原因""退款统计"
   - 排除条件：只查退款金额或笔数（"退了多少款""有几笔退款"）→ 走 nl2sql
   - 关键词：退款、退货、退款率、退款原因、退款分析、退款统计

4. **顾客消费分析**（id: customer_consumption_analysis）
   - 用途：分析顾客消费行为，包括消费金额、频次分布、来源渠道
   - 适用场景：用户想"分析顾客消费""会员分析""顾客画像"
   - 排除条件：只查顾客数量或信息（"有多少顾客""今天来了几个新顾客"）→ 走 nl2sql
   - 关键词：顾客、消费、会员、客户

5. **员工绩效**（id: staff_performance）
   - 用途：分析员工绩效表现，包括核销数排行、考勤统计
   - 适用场景：用户想"看看员工表现""业绩排行""员工绩效分析"
   - 排除条件：只查员工信息或单个员工数据（"有哪些员工""张三今天核销了多少"）→ 走 nl2sql
   - 关键词：员工、绩效、业绩、核销、销售额、排行

6. **月度对比**（id: monthly_comparison）
   - 用途：对比本月和上月的经营数据，包括营收、订单数等
   - 适用场景：用户想"对比这个月和上个月""环比增长了多少"
   - 排除条件：只查某个月的数据（"上个月营收多少"）→ 走 nl2sql
   - 关键词：对比、比较、本月、上月、环比、增长

7. **库存查询**（id: inventory_query）
   - 用途：查询整体库存状态和预警信息
   - 适用场景：用户想"看看库存情况""有哪些物料缺货"
   - 排除条件：只查某个具体物料的库存（"洗衣液还有多少"）→ 走 nl2sql
   - 关键词：库存、物料、货物、存货、缺货

8. **收支查询**（id: revenue_expense_query）
   - 用途：同时查询收入与支出数据
   - 适用场景：用户想同时看"收入和支出情况""本月赚了多少花了多少"
   - 排除条件：只查收入或只查支出（"这个月支出多少""收入多少"）→ 走 nl2sql
   - 关键词：收入、支出、收支、利润、盈亏、赚、花

## 判断任务

请判断以下问题，并返回所有判断结果：

### 1. 输入是否有效？

有效的输入：有意义的问题、请求、操作指令、问候
无效的输入：无意义字符、测试输入、不完整输入、纯表情

### 2. 是否匹配到高优先级 Skill？

Skill 是**多步骤综合分析工具**，不是普通的查询接口。以下原则决定是否匹配：

匹配原则：
- ✅ 匹配：问题意图为"全面分析/全方位了解"，涉及多个维度
- ❌ 不匹配：问题只涉及一个具体指标或一个具体数据，应走 nl2sql

判断方法：
1. 看问题的**意图**：是要"全面分析"还是只要"一个数字"？
2. 看问题的**范围**：涉及多个维度（营收+顾客+支出）还是单一维度？
3. 看问题的**措辞**：包含"分析""情况""总结""怎么样"等综合词？还是只问了数据？
- 如果匹配到，返回 matched_skill 字段，包含匹配的 Skill ID
- 如果没有匹配到，matched_skill 返回 null

### 3. 是否是上下文相关问题？

判断方法：用户的问题是否需要结合之前的对话才能理解？

- 是：引用之前的内容（"那林志玲的呢"）、纠正之前的回答（"处理中不就是待处理嘛"）、确认之前的结论
- 否：全新的问题

### 4. 是否需要追问？

判断方法：用户的问题是否有足够的信息来执行？

- 需要追问：缺少关键信息，且对话历史中也没有（如只说"退款"，没说哪个顾客）
- 不需要追问：意图清晰，或可从对话历史推断

### 5. 用户想要什么？

判断用户当前的**真实意图**，从以下三种中选择：

**A. 执行操作**（is_operation=true, need_requery=false）
用户想要执行一个具体的操作（退款、发放优惠券、核销等）

**B. 获取数据**（is_operation=false, need_requery=true）
用户想要查询数据库获取信息，包括：
- 查询新数据："今天营业额多少"
- 验证/核实已有数据："再次确认金额统计是否正确"、"帮我再查一下"
- 获取更新的数据："重新查一下今天的库存"
- 追问数据相关问题："5月份的你为什么不查询？"、"这个数据对吗？"、"为什么退款这么多？"
- 质疑数据准确性："你确定只有2笔？"、"这个金额对吗？"

**C. 对话交流**（is_operation=false, need_requery=false）
用户想要讨论、解释、确认已有信息，不需要查询数据库：
- 纠正/确认："处理中不就是待处理嘛"、"你说的对"
- 闲聊/问候："你好"、"好的"
- 纯文本追问："为什么这么说"（不需要查数据）

### 操作类请求的追问规则（重要）

如果用户的问题是操作类请求，即使缺少参数，也不要追问。操作类请求缺少参数时，路由到对应的工具，让工具的确认弹窗让用户填写。

判断方法：
1. 用户的请求是否包含明确的操作动词？（入库、退款、发放、核销、回复、发送、拒绝、批准、同意）
2. 用户是否指定了操作对象？（洗衣液、张三、优惠券）
3. 如果动词+对象都有 → 意图明确，不需要追问
4. 如果只有动词没有对象 → 可能需要追问
5. 如果动词和对象都没有 → 需要追问

示例：
- "物料库存加入这个洗衣液" → 意图明确（入库洗衣液），不需要追问
- "拒绝退款" → 意图明确（拒绝退款），不需要追问
- "退款" → 意图不明确（哪个顾客？批准还是拒绝？），需要追问
- "帮我处理一下" → 意图完全不明确，需要追问

### 特殊情况：确认性回复

当用户回复"是的"、"对"、"是"、"确认"、"好的"等确认性词语时，需要根据对话历史判断确认的内容：

1. 查看对话历史中助手的上一个问题
2. 判断助手问题的性质：
   - 助手问的是"是否要查询XX数据" → B（获取数据）
   - 助手问的是"是否要执行XX操作" → A（执行操作）
   - 助手问的是文本确认 → C（对话交流）

示例：
- 助手: "请问具体指哪两个的金额？" → 用户: "是的" → B（查询金额）
- 助手: "确定要退款吗？" → 用户: "是的" → A（执行退款）
- 助手: "我理解对了吗？" → 用户: "是的" → C（文本确认）

判断方法：
- 如果用户的问题**需要从数据库获取信息**才能回答 → B
- 如果用户的问题**基于对话历史的文字就能回答** → C
- 如果用户想要**执行一个具体操作** → A
- 如果用户是**确认性回复**，根据助手上一个问题的性质判断

## 路由决策

根据第 5 节的判断：
- A（执行操作）→ 继续路由到工具
- B（获取数据）→ 继续路由到 nl2sql
- C（对话交流）→ 直接返回 LLM Agent

其他优先级：
- is_valid=false → 无效输入，返回提示
- need_clarify=true → 需要追问
- matched_skill != null → 优先使用 Skill 执行

## 输出格式
返回 JSON：
{{"is_valid": true/false, "is_context_question": true/false, "need_clarify": false, "is_operation": true/false, "need_requery": false, "matched_skill": "skill_id 或 null", "reason": "判断原因（简短说明）", "missing_info": "缺少的信息（仅 need_clarify=true 时填写）"}}

【重要】输出格式要求：
1. 只返回一个完整的 JSON 对象
2. 不要包含任何其他文字、解释或 markdown 代码块标记
3. 所有字符串必须用双引号
4. 布尔值必须是 true/false（小写）
5. matched_skill 如果没有匹配到，返回 null（不是字符串"null"）"""
            
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
    
    async def _check_question(self, question: str, shop_name: str = "", history_context: str = "") -> dict:
        """
        综合检查用户问题（合并有效性、上下文、追问三个检查）
        
        一次 LLM 调用完成三个判断：
        1. is_valid: 输入是否有效
        2. is_context_question: 是否是上下文相关问题
        3. need_clarify: 是否需要追问
        
        Args:
            question: 用户问题
            shop_name: 店铺名称
            history_context: 对话历史上下文
        
        Returns:
            {"is_valid": bool, "is_context_question": bool, "need_clarify": bool, "reason": str, "missing_info": str}
        """
        question = question.strip()
        
        # 快速问题示例
        default_quick_questions = [
            "今天营业额多少？",
            "本月经营情况如何？",
            "有哪些套餐？",
            "库存还有多少？",
        ]
        
        # 1. 规则检查：快速判断无效输入
        import re
        
        if len(question) < 2:
            return {
                "is_valid": False,
                "is_context_question": False,
                "need_clarify": False,
                "reason": "输入太短",
                "missing_info": "",
                "quick_questions": default_quick_questions
            }
        
        if re.match(r'^[\d\s\.\+\-\*\/\=\!\@\#\$\%\^\&\(\)]+$', question):
            return {
                "is_valid": False,
                "is_context_question": False,
                "need_clarify": False,
                "reason": "纯数字或特殊字符",
                "missing_info": "",
                "quick_questions": default_quick_questions
            }
        
        if len(set(question.replace(' ', ''))) == 1:
            return {
                "is_valid": False,
                "is_context_question": False,
                "need_clarify": False,
                "reason": "无意义的重复字符",
                "missing_info": "",
                "quick_questions": default_quick_questions
            }
        
        # 2. LLM 综合判断
        try:
            history_section = ""
            if history_context:
                history_section = f"""
## 对话历史
{history_context}
"""
            
            shop_section = ""
            if shop_name:
                shop_section = f"""
## 店铺信息
店铺名称：{shop_name}
"""
            
            prompt = f"""你是店铺智能助手的路由判断模块。你的职责是帮助店长管理店铺，包括查询数据（营业额、顾客、库存）、执行操作（退款审批、优惠券发放、核销）、回答问题。

判断用户输入的性质，决定如何处理。

## 用户输入
"{question}"
{history_section}
{shop_section}

## 高优先级 Skills
以下是系统预设的高优先级 Skills。Skill 是**预定义的多步骤综合分析工具**，适合需要查询多个维度数据并汇总的复杂问题。
**单一指标查询（如只问一个数字或一个指标）不应匹配 Skill，应直接走 nl2sql。**

【匹配原则】
- ✅ 应匹配：问题包含"分析""情况""综合""总结"等综合分析关键词，需要多方面数据
- ❌ 不应匹配：问题只是查询某个具体单一指标（如"今天营业额多少""本月营收多少""退了多少款"）

【各 Skill 详细说明】

1. **今日经营概况**（id: daily_business_summary）
   - 用途：综合展示今天的经营全貌，包括营业额、核销数、新顾客、热销套餐、库存预警
   - 适用场景：用户想"看看今天怎么样""了解一下今天的情况"
   - 排除条件：只问单一指标（"今天营业额多少""今天核销了多少单"）→ 走 nl2sql
   - 关键词：今天、今日、日报、当天、今日概况、今日经营

2. **本月经营情况分析**（id: monthly_business_analysis）
   - 用途：综合分析本月经营状况，包括营收、顾客、支出、退款、热销套餐等多维度数据
   - 适用场景：用户想"分析一下本月情况""本月经营怎么样""做个月报"
   - 排除条件：只问本月某个单一指标（"本月营收多少""本月利润多少""这个月来了多少顾客"）→ 走 nl2sql
   - 关键词：本月、经营、情况、分析、月度、这个月、月报

3. **退款分析**（id: refund_analysis）
   - 用途：综合分析退款情况，包括状态分布、原因分布、趋势
   - 适用场景：用户想"分析退款情况""看看退款原因""退款统计"
   - 排除条件：只查退款金额或笔数（"退了多少款""有几笔退款"）→ 走 nl2sql
   - 关键词：退款、退货、退款率、退款原因、退款分析、退款统计

4. **顾客消费分析**（id: customer_consumption_analysis）
   - 用途：分析顾客消费行为，包括消费金额、频次分布、来源渠道
   - 适用场景：用户想"分析顾客消费""会员分析""顾客画像"
   - 排除条件：只查顾客数量或信息（"有多少顾客""今天来了几个新顾客"）→ 走 nl2sql
   - 关键词：顾客、消费、会员、客户

5. **员工绩效**（id: staff_performance）
   - 用途：分析员工绩效表现，包括核销数排行、考勤统计
   - 适用场景：用户想"看看员工表现""业绩排行""员工绩效分析"
   - 排除条件：只查员工信息或单个员工数据（"有哪些员工""张三今天核销了多少"）→ 走 nl2sql
   - 关键词：员工、绩效、业绩、核销、销售额、排行

6. **月度对比**（id: monthly_comparison）
   - 用途：对比本月和上月的经营数据，包括营收、订单数等
   - 适用场景：用户想"对比这个月和上个月""环比增长了多少"
   - 排除条件：只查某个月的数据（"上个月营收多少"）→ 走 nl2sql
   - 关键词：对比、比较、本月、上月、环比、增长

7. **库存查询**（id: inventory_query）
   - 用途：查询整体库存状态和预警信息
   - 适用场景：用户想"看看库存情况""有哪些物料缺货"
   - 排除条件：只查某个具体物料的库存（"洗衣液还有多少"）→ 走 nl2sql
   - 关键词：库存、物料、货物、存货、缺货

8. **收支查询**（id: revenue_expense_query）
   - 用途：同时查询收入与支出数据
   - 适用场景：用户想同时看"收入和支出情况""本月赚了多少花了多少"
   - 排除条件：只查收入或只查支出（"这个月支出多少""收入多少"）→ 走 nl2sql
   - 关键词：收入、支出、收支、利润、盈亏、赚、花

## 判断任务

请判断以下问题，并返回所有判断结果：

### 1. 输入是否有效？

有效的输入：有意义的问题、请求、操作指令、问候
无效的输入：无意义字符、测试输入、不完整输入、纯表情

### 2. 是否匹配到高优先级 Skill？

Skill 是**多步骤综合分析工具**，不是普通的查询接口。以下原则决定是否匹配：

匹配原则：
- ✅ 匹配：问题意图为"全面分析/全方位了解"，涉及多个维度
- ❌ 不匹配：问题只涉及一个具体指标或一个具体数据，应走 nl2sql

判断方法：
1. 看问题的**意图**：是要"全面分析"还是只要"一个数字"？
2. 看问题的**范围**：涉及多个维度（营收+顾客+支出）还是单一维度？
3. 看问题的**措辞**：包含"分析""情况""总结""怎么样"等综合词？还是只问了数据？
- 如果匹配到，返回 matched_skill 字段，包含匹配的 Skill ID
- 如果没有匹配到，matched_skill 返回 null

### 3. 是否是上下文相关问题？

判断方法：用户的问题是否需要结合之前的对话才能理解？

- 是：引用之前的内容（"那林志玲的呢"）、纠正之前的回答（"处理中不就是待处理嘛"）、确认之前的结论
- 否：全新的问题

### 4. 是否需要追问？

判断方法：用户的问题是否有足够的信息来执行？

- 需要追问：缺少关键信息，且对话历史中也没有（如只说"退款"，没说哪个顾客）
- 不需要追问：意图清晰，或可从对话历史推断

### 5. 用户想要什么？

判断用户当前的**真实意图**，从以下三种中选择：

**A. 执行操作**（is_operation=true, need_requery=false）
用户想要执行一个具体的操作（退款、发放优惠券、核销等）

**B. 获取数据**（is_operation=false, need_requery=true）
用户想要查询数据库获取信息，包括：
- 查询新数据："今天营业额多少"
- 验证/核实已有数据："再次确认金额统计是否正确"、"帮我再查一下"
- 获取更新的数据："重新查一下今天的库存"
- 追问数据相关问题："5月份的你为什么不查询？"、"这个数据对吗？"、"为什么退款这么多？"
- 质疑数据准确性："你确定只有2笔？"、"这个金额对吗？"

**C. 对话交流**（is_operation=false, need_requery=false）
用户想要讨论、解释、确认已有信息，不需要查询数据库：
- 纠正/确认："处理中不就是待处理嘛"、"你说的对"
- 闲聊/问候："你好"、"好的"
- 纯文本追问："为什么这么说"（不需要查数据）

### 操作类请求的追问规则（重要）

如果用户的问题是操作类请求，即使缺少参数，也不要追问。操作类请求缺少参数时，路由到对应的工具，让工具的确认弹窗让用户填写。

判断方法：
1. 用户的请求是否包含明确的操作动词？（入库、退款、发放、核销、回复、发送、拒绝、批准、同意）
2. 用户是否指定了操作对象？（洗衣液、张三、优惠券）
3. 如果动词+对象都有 → 意图明确，不需要追问
4. 如果只有动词没有对象 → 可能需要追问
5. 如果动词和对象都没有 → 需要追问

示例：
- "物料库存加入这个洗衣液" → 意图明确（入库洗衣液），不需要追问
- "拒绝退款" → 意图明确（拒绝退款），不需要追问
- "退款" → 意图不明确（哪个顾客？批准还是拒绝？），需要追问
- "帮我处理一下" → 意图完全不明确，需要追问

### 特殊情况：确认性回复

当用户回复"是的"、"对"、"是"、"确认"、"好的"等确认性词语时，需要根据对话历史判断确认的内容：

1. 查看对话历史中助手的上一个问题
2. 判断助手问题的性质：
   - 助手问的是"是否要查询XX数据" → B（获取数据）
   - 助手问的是"是否要执行XX操作" → A（执行操作）
   - 助手问的是文本确认 → C（对话交流）

示例：
- 助手: "请问具体指哪两个的金额？" → 用户: "是的" → B（查询金额）
- 助手: "确定要退款吗？" → 用户: "是的" → A（执行退款）
- 助手: "我理解对了吗？" → 用户: "是的" → C（文本确认）

判断方法：
- 如果用户的问题**需要从数据库获取信息**才能回答 → B
- 如果用户的问题**基于对话历史的文字就能回答** → C
- 如果用户想要**执行一个具体操作** → A
- 如果用户是**确认性回复**，根据助手上一个问题的性质判断

## 路由决策

根据第 5 节的判断：
- A（执行操作）→ 继续路由到工具
- B（获取数据）→ 继续路由到 nl2sql
- C（对话交流）→ 直接返回 LLM Agent

其他优先级：
- is_valid=false → 无效输入，返回提示
- need_clarify=true → 需要追问
- matched_skill != null → 优先使用 Skill 执行

## 输出格式
返回 JSON：
{{"is_valid": true/false, "is_context_question": true/false, "need_clarify": false, "is_operation": true/false, "need_requery": false, "matched_skill": "skill_id 或 null", "reason": "判断原因（简短说明）", "missing_info": "缺少的信息（仅 need_clarify=true 时填写）"}}

【重要】输出格式要求：
1. 只返回一个完整的 JSON 对象
2. 不要包含任何其他文字、解释或 markdown 代码块标记
3. 所有字符串必须用双引号
4. 布尔值必须是 true/false（小写）
5. matched_skill 如果没有匹配到，返回 null（不是字符串"null"）"""

            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            from app.utils.json_parser import safe_parse_json
            result = safe_parse_json(response.content.strip())
            
            if result and isinstance(result, dict):
                # 确保所有字段存在
                result.setdefault("is_valid", True)
                result.setdefault("is_context_question", False)
                result.setdefault("need_clarify", False)
                result.setdefault("is_operation", False)
                result.setdefault("need_requery", False)
                result.setdefault("matched_skill", None)
                result.setdefault("reason", "")
                result.setdefault("missing_info", "")
                result["quick_questions"] = default_quick_questions
                return result
            
            # 解析失败，默认有效
            return {"is_valid": True, "is_context_question": False, "need_clarify": False, "is_operation": False, "need_requery": False, "reason": "判断失败", "missing_info": "", "quick_questions": default_quick_questions}
        except Exception as e:
            print(f"[Router] 问题检查失败: {str(e)}")
            return {"is_valid": True, "is_context_question": False, "need_clarify": False, "is_operation": False, "need_requery": False, "reason": "判断异常", "missing_info": "", "quick_questions": default_quick_questions}
    
    def _generate_dynamic_quick_questions(self, question: str, missing_info: str, history_context: str) -> list:
        """
        根据追问上下文生成动态快捷问题
        
        Args:
            question: 用户问题
            missing_info: 缺少的信息
            history_context: 对话历史
        
        Returns:
            动态快捷问题列表
        """
        # 默认问题
        default = [
            "今天营业额多少？",
            "本月经营情况如何？",
            "有哪些套餐？",
            "库存还有多少？",
        ]
        
        question_lower = question.lower()
        missing_lower = (missing_info or "").lower()
        
        # 根据缺失信息生成相关问题
        if "数量" in missing_lower or "入库" in question_lower or "库存" in question_lower or "物料" in question_lower:
            return ["入库1瓶", "入库10瓶", "入库1箱", "查看库存"]
        
        if "退款" in question_lower or "退款" in str(history_context or "").lower():
            return ["查看退款记录", "查询待处理退款", "本月退款统计", "退款原因分析"]
        
        if "顾客" in question_lower or "客户" in question_lower:
            return ["查询顾客信息", "查看顾客消费记录", "查询顾客余额", "新增顾客"]
        
        if "优惠券" in question_lower or "券" in question_lower:
            return ["查看优惠券列表", "查询优惠券使用记录", "发放优惠券"]
        
        if "员工" in question_lower or "排班" in question_lower:
            return ["查看员工列表", "查询员工绩效", "查看排班"]
        
        if "套餐" in question_lower:
            return ["查看套餐列表", "套餐销售统计", "新增套餐"]
        
        if "评价" in question_lower or "反馈" in question_lower:
            return ["查看评价列表", "待回复评价", "评价统计"]
        
        if "营业额" in question_lower or "收入" in question_lower:
            return ["今日营业额", "本月营业额", "收支查询"]
        
        # 根据历史对话推断
        if history_context:
            history_lower = history_context.lower()
            if "退款" in history_lower:
                return ["查看退款记录", "查询待处理退款", "本月退款统计"]
            if "顾客" in history_lower:
                return ["查询顾客信息", "查看顾客消费记录"]
            if "库存" in history_lower or "物料" in history_lower:
                return ["查看库存", "库存预警", "入库操作"]
        
        return default
    
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
        
        # 3. 综合检查（合并有效性、上下文、追问三个检查）
        shop_name = ""
        if shop_context:
            for line in shop_context.split("\n"):
                if "店铺名称" in line:
                    shop_name = line.split("：")[-1].strip() if "：" in line else line.split(":")[-1].strip()
                    break
        
        check_result = await self._check_question(task, shop_name, history_context)
        print(f"[Router] 问题检查结果: valid={check_result.get('is_valid')}, context={check_result.get('is_context_question')}, clarify={check_result.get('need_clarify')}, requery={check_result.get('need_requery')}, operation={check_result.get('is_operation')}, matched_skill={check_result.get('matched_skill')}, reason={check_result.get('reason')}")
        
        # 4. 检查是否匹配到高优先级 Skill（LLM 判断为主）
        if check_result.get("matched_skill"):
            skill_id = check_result["matched_skill"]
            skill_manager = get_skill_manager()
            skill = skill_manager.get_skill(skill_id)
            if skill:
                # 用 SkillManager.match() 做代码级校验（仅日志，LLM 判断为准）
                code_match = skill_manager.match(task)
                if code_match:
                    code_skill, code_score = code_match
                    if code_skill.id != skill_id:
                        print(f"[Router] ⚠️ LLM匹配({skill_id})与代码匹配({code_skill.id},score={code_score:.2f})不一致，以LLM为准")
                else:
                    print(f"[Router] ⚠️ LLM匹配Skill({skill_id})但代码未匹配(score<0.5)，以LLM为准")
                print(f"[Router] LLM 匹配到预设 Skill: {skill.name}")
                return {
                    "mode": "single",
                    "agent": None,
                    "reasoning": f"匹配预设 Skill: {skill.name}",
                    "understanding": task,
                    "analysis": "",
                    "plan": [{"step": step.step, "action": step.task, "tool": step.agent} for step in skill.steps],
                    "complexity": "complex" if len(skill.steps) > 1 else "simple",
                }
        
        # 路由决策（按优先级顺序）
        
        # 5a. 无效输入
        if not check_result.get("is_valid"):
            return {
                "mode": "clarify",
                "agent": None,
                "reasoning": check_result.get("reason", "问题不明确"),
                "understanding": task,
                "analysis": "",
                "plan": [],
                "complexity": "simple",
                "clarification": "我没有理解您的意思，请问您想了解什么？",
                "quick_questions": check_result.get("quick_questions", [])
            }
        
        # 4b. 需要追问（生成动态快捷问题）
        if check_result.get("need_clarify"):
            missing_info = check_result.get("missing_info", "")
            print(f"[Router] 需要追问，缺少信息: {missing_info}")
            
            # 生成动态快捷问题
            dynamic_questions = self._generate_dynamic_quick_questions(task, missing_info, history_context)
            
            return {
                "mode": "clarify",
                "agent": None,
                "reasoning": check_result.get("reason", "问题需要更多信息"),
                "understanding": task,
                "analysis": "",
                "plan": [],
                "complexity": "simple",
                "clarification": f"请问{missing_info}？" if missing_info else "请问您想了解什么？",
                "quick_questions": dynamic_questions
            }
        
        # 4c. 纯文本上下文问题（不需要查询数据库，不需要执行操作）
        if check_result.get("is_context_question") and not check_result.get("is_operation") and not check_result.get("need_requery"):
            return {
                "mode": "single",
                "agent": AgentType.LLM,
                "reasoning": check_result.get("reason", "上下文相关问题"),
                "understanding": "用户在追问之前对话中的内容",
                "analysis": "这是一个上下文相关问题，需要结合历史对话理解",
                "plan": [{"step": 1, "action": "基于上下文回答", "tool": "llm", "is_critical": True}],
                "complexity": "simple"
            }
        
        # 4d. 其他情况 → 继续路由到 COMPLEXITY_PROMPT
        # 包括：新问题、操作类上下文问题、需要重新查询的上下文问题
        # need_requery 作为上下文传递给 COMPLEXITY_PROMPT
        
        # 4. 检查缓存
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
            
            # 添加 need_requery 上下文（用户需要查询数据）
            if check_result.get("need_requery"):
                prompt += """

## 重要：用户需要查询数据
用户的问题需要从数据库获取信息才能回答。请使用 nl2sql 生成 SQL 查询。
"""
            
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
            
            response = await self.llm.bind(response_format={"type": "json_object"}).ainvoke([HumanMessage(content=prompt)])
            
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
            
            # 打印 LLM 原始返回（用于调试）
            print(f"[Router] LLM返回({len(content)}字符): {content[:2000]}")
            
            # 非 dict 结果视为无效（如 JSON 字符串字面量 "mode"），触发重试
            if isinstance(result, str):
                print(f"[Router] 解析结果为字符串而非 JSON 对象: {result}")
                result = None
            
            # JSON 解析失败时重试
            max_retries = 2
            retry_count = 0
            while not result and retry_count < max_retries:
                retry_count += 1
                print(f"[Router] JSON 解析失败，重试 {retry_count}/{max_retries}")
                print(f"[Router] LLM返回内容({len(content)}字符): {content[:2000]}")
                retry_prompt = prompt + "\n\n【重要】你上次返回的是单独的 JSON 字符串，不是完整的 JSON 对象。必须返回包含 mode、agent、reasoning、understanding、analysis、plan、complexity 等全部字段的完整 JSON 对象 {{...}}，禁止返回裸字符串。"
                response = await self.llm.bind(response_format={"type": "json_object"}).ainvoke([HumanMessage(content=retry_prompt)])
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
                # 重试结果也需校验非 dict 情况
                if isinstance(result, str):
                    print(f"[Router] 重试解析结果仍为字符串: {result}")
                    result = None
            
            if not result:
                # 重试都失败，根据关键词判断意图选择 fallback
                operation_keywords = ["发放", "退款", "核销", "入库", "出库", "通知", "回复", "重试", "拒绝", "批准", "查", "查询", "搜索"]
                is_operation = any(kw in task for kw in operation_keywords)
                data_query_keywords = ["余额", "钱包", "多少", "查看", "列表", "统计", "总", "金额", "信息", "列", "列出", "基本"]
                is_data_query = any(kw in task for kw in data_query_keywords)

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
                elif is_data_query:
                    print(f"[Router] JSON 解析失败（重试{retry_count}次），检测到数据查询类请求，fallback 到 NL2SQL")
                    return {
                        "mode": "single",
                        "agent": AgentType.NL2SQL,
                        "reasoning": f"JSON 解析失败（重试{retry_count}次），检测到数据查询关键词，fallback 到 NL2SQL",
                        "understanding": f"用户想要{task}",
                        "analysis": "",
                        "plan": [{"step": 1, "action": task, "tool": "数据查询", "is_critical": True}],
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
            
            if result.get("mode") == "single" and result.get("agent") not in [AgentType.RAG, AgentType.NL2SQL, AgentType.TOOL, AgentType.VISION, AgentType.LLM]:
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
            
            # 保存到缓存（TTLCache 自动管理淘汰，无需手动 clear）
            _plan_cache[cache_key] = result
            
            return result
        except Exception as e:
            print(f"[Router] 路由判断失败: {str(e)}")
            print(f"[Router] LLM原始返回({len(content)}字符): {content}")
            operation_keywords = ["发放", "退款", "核销", "入库", "出库", "通知", "回复", "重试", "拒绝", "批准", "查", "查询", "搜索"]
            is_operation = any(kw in task for kw in operation_keywords)
            data_query_keywords = ["余额", "钱包", "多少", "查看", "列表", "统计", "总", "金额", "信息", "列", "列出", "基本"]
            is_data_query = any(kw in task for kw in data_query_keywords)

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
            elif is_data_query:
                print(f"[Router] 路由判断失败，检测到数据查询类请求，fallback 到 NL2SQL")
                return {
                    "mode": "single",
                    "agent": AgentType.NL2SQL,
                    "reasoning": f"路由判断失败，检测到数据查询关键词，fallback 到 NL2SQL: {str(e)}",
                    "understanding": f"用户想要{task}",
                    "analysis": "",
                    "plan": [{"step": 1, "action": task, "tool": "数据查询", "is_critical": True}],
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
            print(f"[Router] LLM原始返回({len(content)}字符): {content[:300]}...")
            
            # 提取 JSON
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
                print(f"[Router] 提取JSON代码块: {content[:200]}...")
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()
                print(f"[Router] 提取代码块: {content[:200]}...")
            
            result = safe_parse_json(content)
            
            # JSON 解析失败时重试
            max_retries = 2
            retry_count = 0
            while not result and retry_count < max_retries:
                retry_count += 1
                print(f"[Router] JSON 解析失败，重试 {retry_count}/{max_retries}")
                print(f"[Router] LLM返回内容({len(content)}字符): {content[:2000]}")
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
                elif is_data_query:
                    print(f"[Router] JSON 解析失败（重试{retry_count}次），检测到数据查询类请求，fallback 到 NL2SQL")
                    return {
                        "mode": "single",
                        "agent": AgentType.NL2SQL,
                        "reasoning": f"JSON 解析失败（重试{retry_count}次），检测到数据查询关键词，fallback 到 NL2SQL",
                        "understanding": f"用户想要{task}",
                        "analysis": "",
                        "plan": [{"step": 1, "action": task, "tool": "数据查询", "is_critical": True}],
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
            
            if result.get("mode") == "single" and result.get("agent") not in [AgentType.RAG, AgentType.NL2SQL, AgentType.TOOL, AgentType.VISION, AgentType.LLM]:
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
            
            # 保存到缓存（TTLCache 自动管理淘汰，无需手动 clear）
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
