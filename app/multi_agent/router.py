"""
智能路由模块（优化版）
使用 LLM 一次性完成问题理解和任务分配
"""

import json
import hashlib
from typing import Dict, Any, Optional, List
from app.llm import get_chat_llm
from app.multi_agent.protocol import TaskPlan, TaskComplexity, AgentType, SubTask
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
- tool: 工具调用（查询顾客信息、排班表、优惠券等）
- llm: 上下文分析、追问解释、总结建议（基于已有信息回答，不需要查询数据）
- vision: 图像理解（OCR文字识别、图像分析等）

## 判断规则（按优先级）

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
- 实时信息类："今天天气怎么样？"、"最近有什么新闻？"

### 3. 数据查询问题 → single + nl2sql/tool
需要查询当前店铺的具体数据：
- 查询类："今天营业额多少？"、"有多少顾客？"
- 统计类："本月销售排名？"、"库存还有多少？"
- 省略句：结合历史对话理解（如"本月呢？" → "本月的收入"）

### 4. 综合分析问题 → multi
需要先查询数据，再进行分析：
- 分析类："分析本月经营情况"、"为什么业绩下降了？"
- 报告类："生成本月经营报告"

## 输出格式

请返回严格的 JSON 格式：

{{
    "mode": "single 或 multi",
    "agent": "rag/nl2sql/tool/llm/vision"（single 模式时）,
    "reasoning": "判断原因",
    "is_knowledge_question": true/false,
    "understanding": "用户想要XXX（如果是省略句或追问，要写出完整意图）",
    "analysis": "分析问题的核心需求",
    "plan": [
        {{
            "step": 1,
            "action": "查询XXX",
            "tool": "数据查询",
            "is_critical": true
        }}
    ],
    "complexity": "simple/medium/complex"
}}"""


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
            "tool": "数据查询",
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
            "tool": "数据查询",
            "purpose": "获取本月销售额、订单数、热销套餐等",
            "expected": "获得本月销售汇总数据",
            "is_critical": true,
            "depends_on": []
        }},
        {{
            "step": 2,
            "action": "查询本月顾客数据",
            "tool": "数据查询",
            "purpose": "获取本月新顾客数、活跃顾客数等",
            "expected": "获得本月顾客统计",
            "is_critical": true,
            "depends_on": []
        }},
        {{
            "step": 3,
            "action": "查询本月支出数据",
            "tool": "数据查询",
            "purpose": "获取本月各类支出明细",
            "expected": "获得本月支出汇总",
            "is_critical": true,
            "depends_on": []
        }},
        {{
            "step": 4,
            "action": "综合分析经营情况",
            "tool": "知识检索",
            "purpose": "分析销售、顾客、支出数据，找出问题和机会",
            "expected": "得出经营分析结论",
            "is_critical": true,
            "depends_on": [1, 2, 3]
        }},
        {{
            "step": 5,
            "action": "生成改进建议",
            "tool": "知识检索",
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

可用 Agent 类型：
- nl2sql: 数据查询（营业额、顾客数、库存、员工绩效、财务数据等）
- tool: 工具调用（查询顾客信息、排班表、优惠券等）
- llm: 总结分析建议（基于数据进行分析、总结、给出建议）
- rag: 知识问答（定义、解释、行业知识、规则政策等）
- vision: 图像理解（OCR文字识别、图像分析等）

## 重要规则（必须遵守）

### Agent 选择规则
1. **查询店铺数据** → 使用 nl2sql（营业额、订单、顾客、库存等）
2. **分析/总结/建议** → 使用 llm（基于数据进行分析、给出建议）
3. **知识问答** → 使用 rag（定义、解释、行业知识、规则政策）
4. **工具操作** → 使用 tool（查询顾客信息、排班表等）

### 经营分析类任务
当用户要求"分析经营情况"、"经营报告"时：
- 数据查询部分 → 使用 nl2sql
- 分析总结部分 → 使用 llm（不是 rag！）

### 关键区别
- **llm**：基于提供的数据进行分析总结（不检索知识库，不搜索互联网）
- **rag**：检索知识库回答问题（用于定义、解释、行业知识）

## 拆分规则
1. 每个子任务应该明确指定使用哪个 Agent
2. 子任务之间应该清晰分离，避免重复
3. 保持原始任务的语义，不要遗漏信息
4. 如果子任务之间有依赖关系，必须指定 depends_on

## 示例

示例1（经营分析）：
任务："分析本月经营情况"
拆分结果：
[
    {{"id": 1, "task": "查询本月营收数据", "agent": "nl2sql", "description": "查询本月营业额、订单数、热销套餐", "depends_on": []}},
    {{"id": 2, "task": "查询本月顾客数据", "agent": "nl2sql", "description": "查询本月新顾客数、活跃顾客数", "depends_on": []}},
    {{"id": 3, "task": "查询本月支出数据", "agent": "nl2sql", "description": "查询本月各类支出", "depends_on": []}},
    {{"id": 4, "task": "汇总分析并给出建议", "agent": "llm", "description": "基于以上数据进行分析并给出建议", "depends_on": [1, 2, 3]}}
]

示例2（知识问答）：
任务："什么是RFM模型？如何应用？"
拆分结果：
[
    {{"id": 1, "task": "解释RFM模型", "agent": "rag", "description": "从知识库获取RFM模型的定义和原理", "depends_on": []}},
    {{"id": 2, "task": "RFM模型应用场景", "agent": "rag", "description": "从知识库获取RFM模型的应用方法", "depends_on": []}}
]

示例3（混合任务）：
任务："查询本月业绩，分析趋势，给出建议"
拆分结果：
[
    {{"id": 1, "task": "查询本月业绩数据", "agent": "nl2sql", "description": "查询本月的营业额和订单数", "depends_on": []}},
    {{"id": 2, "task": "分析业绩趋势并给出建议", "agent": "llm", "description": "基于数据进行趋势分析和建议", "depends_on": [1]}}
]

请返回 JSON 格式的数组：
[
    {{"id": 1, "task": "子任务描述", "agent": "agent类型", "description": "任务说明", "depends_on": []}},
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
    
    async def _check_need_clarification(self, question: str, shop_name: str = "") -> dict:
        """
        检查是否需要追问
        
        Args:
            question: 用户问题
            shop_name: 店铺名称（有店铺则跳过店铺相关追问）
        
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
            prompt = f"""判断用户问题是否需要追问才能准确回答。

用户问题："{question}"

需要追问的情况：
1. 问题缺少关键信息（如地点、时间、对象等）
2. 问题有多种理解方式
3. 问题涉及特定上下文但未说明

不需要追问的情况：
1. 问题已经很明确（如"本月营业额"）
2. 问题涉及店铺内部数据（如"库存多少"、"套餐价格"）
3. 问题是通用知识（如"什么是RFM模型"）

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
    
    async def _check_question_validity(self, question: str) -> dict:
        """
        检查问题是否有效（不是无意义内容）
        
        Args:
            question: 用户问题
        
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
            prompt = f"""判断以下用户输入是否是一个有效的问题或请求。

用户输入："{question}"

有效的输入：
- 有明确意图的问题（如"今天营业额多少"）
- 有明确意图的请求（如"帮我查一下库存"）
- 简短但有意义的问候（如"你好"、"在吗"）

无效的输入：
- 无意义的字符（如"111"、"aaa"、"..."）
- 测试输入（如"test"、"测试"）
- 不完整的输入（如"帮我"、"查询"）
- 纯表情符号

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
        路由任务到合适的 Agent（使用 LLM 判断）
        """
        # 1. 图像任务
        if has_image:
            return {
                "mode": "single",
                "agent": AgentType.VISION,
                "reasoning": "包含图像，使用 Vision Agent 处理",
                "understanding": f"用户想要{task}",
                "analysis": "",
                "plan": [{"step": 1, "action": task, "tool": "vision", "is_critical": True}],
                "complexity": "simple"
            }
        
        # 提取历史上下文
        history_context = ""
        if shop_context and "历史对话" in shop_context:
            history_context = shop_context
        
        # 2. 上下文相关问题
        if self._is_context_question(task, history_context):
            return {
                "mode": "single",
                "agent": AgentType.LLM,
                "reasoning": "上下文相关问题，使用 LLM 基于历史回答",
                "understanding": f"用户在追问之前对话中的内容",
                "analysis": "这是一个上下文相关问题，需要结合历史对话理解",
                "plan": [{"step": 1, "action": "基于上下文回答", "tool": "llm", "is_critical": True}],
                "complexity": "simple"
            }
        
        # 3. 检查问题是否有效（不是无意义内容）
        validity = await self._check_question_validity(task)
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
        
        # 4. 检查是否需要追问（在规划任务之前）
        # 提取店铺名称
        shop_name = ""
        if shop_context:
            for line in shop_context.split("\n"):
                if "店铺名称" in line:
                    shop_name = line.split("：")[-1].strip() if "：" in line else line.split(":")[-1].strip()
                    break
        
        clarification = await self._check_need_clarification(task, shop_name)
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
        
        # 5. 使用 LLM 判断问题类型
        try:
            from langchain_core.messages import HumanMessage
            
            prompt = f"""分析用户问题，判断应该使用哪个 Agent 处理，并生成执行计划。

用户问题：{task}

## 重要：plan.action 必须是实际要执行的任务

**plan.action 字段必须是具体的执行任务，而不是用户的原始输入。**

特别是当用户的问题是模糊指代时（如"重试上面这个问题"、"再试一次"）：
- ❌ 错误：{{"action": "重试上面这个问题"}}
- ✅ 正确：{{"action": "查询今天的营业额"}}（从历史对话中找到的实际任务）

示例：
- 用户说："重试上面这个问题"，历史上问过"今天营业额多少"
- plan.action 应该是："查询今天的营业额"

- 用户说："本月呢？"，历史上问过"历史总收入"
- plan.action 应该是："查询本月的总收入"

可用 Agent（tool 字段必须使用以下英文名称）：
- rag: 知识问答、天气、新闻、实时信息、定义、解释、建议
- nl2sql: 数据查询（营业额、支出、收入、顾客数等店铺数据）
- tool: 工具调用（查询顾客信息、排班表、优惠券等）
- llm: 上下文分析、总结建议（基于已有信息回答）

判断规则：
1. 天气、新闻、实时信息 → rag
2. 查询店铺数据 → nl2sql
3. 定义、解释、建议 → rag 或 llm
4. 多个步骤 → multi

⚠️ 重要：tool 字段必须是英文（rag/nl2sql/tool/llm），禁止使用中文！

返回 JSON：
{{
    "agent": "rag/nl2sql/tool/llm",
    "reasoning": "原因",
    "understanding": "用户想要XXX（从历史中推断的真实意图）",
    "plan": [{{"step": 1, "action": "具体执行任务（不是用户原话）", "tool": "rag/nl2sql/tool/llm"}}]
}}"""
            
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            result = safe_parse_json(response.content.strip())
            
            if result and "agent" in result:
                agent_type = result["agent"]
                reasoning = result.get("reasoning", "")
                llm_plan = result.get("plan", [])
                
                # 映射 Agent 类型
                agent_map = {
                    "rag": AgentType.RAG,
                    "nl2sql": AgentType.NL2SQL,
                    "tool": AgentType.TOOL,
                    "llm": AgentType.LLM,
                    "multi": None,
                }
                
                agent = agent_map.get(agent_type, AgentType.LLM)
                
                # 构建默认计划（如果 LLM 没有返回）
                if not llm_plan:
                    llm_plan = [{"step": 1, "action": task, "tool": agent_type, "is_critical": True}]
                
                if agent_type == "multi":
                    return {
                        "mode": "multi",
                        "agent": None,
                        "reasoning": reasoning,
                        "understanding": f"用户想要{task}",
                        "analysis": "",
                        "plan": [],
                        "complexity": "complex"
                    }
                else:
                    return {
                        "mode": "single",
                        "agent": agent,
                        "reasoning": reasoning,
                        "understanding": f"用户想要{task}",
                        "analysis": "",
                        "plan": llm_plan,
                        "complexity": "simple"
                    }
        except Exception as e:
            print(f"[Router] LLM 路由失败: {str(e)}")
        
        # 4. 默认使用 LLM
        return {
            "mode": "single",
            "agent": AgentType.LLM,
            "reasoning": "默认使用 LLM 处理",
            "understanding": f"用户想要{task}",
            "analysis": "",
            "plan": [{"step": 1, "action": task, "tool": "llm", "is_critical": True}],
            "complexity": "simple"
        }
    
    async def route(self, task: str, has_image: bool = False, shop_context: str = "") -> Dict[str, Any]:
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
            if not result:
                return {
                    "mode": "single",
                    "agent": AgentType.RAG,
                    "reasoning": "JSON 解析失败，默认使用 RAG",
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
            # 返回默认结果
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
                    description=sub_task_data.get("description", ""),
                    depends_on=sub_task_data.get("depends_on", []),
                )
                sub_tasks.append(sub_task)
            
            print(f"[TaskRouter] 任务拆分成功: {task} -> {len(sub_tasks)} 个子任务")
            for sub_task in sub_tasks:
                deps = f" (依赖: {sub_task.depends_on})" if sub_task.depends_on else " (无依赖)"
                print(f"  - 子任务{sub_task.id}: {sub_task.task} [{sub_task.agent}]{deps}")
            
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
    
    async def create_plan(self, task: str, has_image: bool = False, shop_context: str = "") -> TaskPlan:
        """
        创建任务执行计划
        
        优先级：
        1. 匹配预设 Skill（最高成功率）
        2. 规则判断任务类型
        
        Args:
            task: 用户任务
            has_image: 是否包含图像
            shop_context: 店铺上下文（包含历史对话）
        
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
