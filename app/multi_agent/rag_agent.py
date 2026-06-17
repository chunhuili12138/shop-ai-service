"""
RAG Agent - 知识问答 Agent
调用现有 RAG 模块进行知识问答
集成经验池学习
集成互联网搜索（实时信息）
集成内容评审
集成 LLM 通用知识回答
"""

import asyncio
import json
from typing import Optional
from app.common.user_context import UserContext
from app.multi_agent.protocol import AgentResult, AgentType
from app.experience.pool import get_experience_pool
from app.utils.json_parser import safe_parse_json


# 内容评审 Prompt
CONTENT_REVIEW_PROMPT = """请检查以下回答是否与用户问题相关。

用户问题：{question}

AI回答：
{answer}

评审标准：
1. 回答是否直接回答了用户的问题？
2. 回答的语言是否与用户问题一致（如用户用中文问，回答也应是中文）？
3. 回答内容是否合理、有价值？

请返回 JSON 格式：
{{
    "is_relevant": true/false,
    "reason": "判断原因",
    "suggestion": "改进建议（如果不相关）"
}}"""


# 搜索关键词优化 Prompt
SEARCH_QUERY_OPTIMIZE_PROMPT = """你是一个搜索优化专家。根据用户问题，生成更精确的搜索关键词。

用户问题：{question}

店铺信息：{shop_context}

要求：
1. 提取问题的核心关键词
2. 如果是店铺经营相关问题，添加"店铺经营"、"实体店"等限定词
3. 如果是行业相关问题，添加具体行业（如"DIY手工"、"亲子游乐"）
4. 移除无关的修饰词
5. 返回 1-2 个优化后的搜索关键词，每行一个

示例：
用户问题：分析一下本周的经营情况
优化关键词：
店铺经营数据分析方法
实体店周报分析指标

用户问题：最近有什么有趣的新闻
优化关键词：
今日热点新闻

请返回优化后的搜索关键词："""


# 追问判断 Prompt
CLARIFICATION_CHECK_PROMPT = """判断用户问题是否需要追问才能准确回答。

用户问题：{question}

需要追问的情况：
1. 问题缺少关键信息（如地点、时间、对象等）
2. 问题有多种理解方式
3. 问题涉及特定上下文但未说明

示例：
- "今天天气怎么样" → 需要追问地点
- "嘉善天气" → 不需要追问（已明确地点）
- "套餐多少钱" → 需要追问哪个套餐
- "本月营业额" → 不需要追问（已明确）

只返回 JSON 格式：
{{"need_clarify": true/false, "reason": "原因", "missing_info": "缺少的信息"}}"""


class RAGAgent:
    """
    RAG Agent - 知识问答

    流程：
    1. 判断是否需要追问 → 是 → 返回追问提示
    2. LLM 判断是否需要互联网搜索 → 是 → 搜索互联网
    3. 检索经验池 → 有结果则返回
    4. 检索知识库 → 有结果且置信度高则返回
    5. LLM 通用知识回答
    6. 兜底：搜索互联网
    """

    # 知识库覆盖范围描述（用于 LLM 判断是否需要搜索互联网）
    KB_SCOPE = """本店铺知识库包含以下内容：
- 套餐信息：价格、类型（单次/周卡/月卡）、时长、包含项目
- 营业时间：开门/关门时间、节假日安排、地址、联系方式
- 退款政策：退款条件、退款流程、退款时效
- 店铺规则：年龄限制、安全须知、预约规则、注意事项
- 助手介绍：我是谁、我能做什么、使用方式、服务范围
- 经营建议：基于店铺数据的分析和建议"""

    async def _should_search_web(
        self, original_question: str, task: str, history_context: str = ""
    ) -> bool:
        """
        用 LLM 判断是否需要搜索互联网

        替代原来的关键词匹配，避免误判（如"当前对话助手"触发"当前"关键词）

        Args:
            original_question: 用户原始问题
            task: Router 分析后的任务描述
            history_context: 历史上下文

        Returns:
            是否需要搜索互联网
        """
        try:
            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage

            llm = get_chat_llm(temperature=0)

            history_section = ""
            if history_context:
                history_section = f"\n【历史对话】\n{history_context}\n"

            prompt = f"""判断用户的问题是否需要搜索互联网来回答。

【知识库覆盖范围】
{self.KB_SCOPE}
{history_section}
【Router 分析的任务】
{task}

【用户原始问题】
{original_question}

判断规则（必须严格遵守）：
1. 用户问店铺内部数据（营业额、顾客、库存、排班、订单等）→ 不需要搜索
2. 用户问助手自身问题（你是谁、你能做什么、怎么用）→ 不需要搜索
3. 用户问通用知识（如何提高营业额、什么是VIP会员、经营建议）→ 不需要搜索
4. 用户问店铺规则、套餐、退款政策 → 不需要搜索
5. 用户问其他城市/地区的天气 → 需要搜索
6. 用户问最近新闻、行业趋势、市场行情 → 需要搜索
7. 如果不确定 → 不需要搜索（宁可不搜，不要搜错）

示例：
- "本月营业额多少" → 不需要搜索（店铺内部数据）
- "你是谁" → 不需要搜索（助手自身问题）
- "如何提高顾客满意度" → 不需要搜索（通用知识）
- "海宁天气" → 需要搜索（外部实时信息）
- "最近手工行业趋势" → 需要搜索（外部行业信息）

只返回 JSON 格式：
{{"need_search": true/false, "reason": "判断原因"}}"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])

            content = response.content.strip()
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()

            result = json.loads(content)
            need_search = result.get("need_search", False)
            reason = result.get("reason", "")

            print(f"[RAGAgent] 互联网搜索判断: need_search={need_search}, reason={reason}")
            return need_search

        except Exception as e:
            print(f"[RAGAgent] 互联网搜索判断失败: {str(e)}")
            return False  # 出错时不搜索
    
    def _resolve_reference(self, task: str, history_context: str) -> str:
        """
        解析模糊指代和追问回答
        
        场景1: "重试上面这个问题" → 从历史中找到上一个问题
        场景2: "嘉善"（回答追问"请问您想了解哪个地方的天气？"）→ 组合成"嘉善天气"
        """
        if not history_context:
            return task
        
        task_stripped = task.strip()
        
        # 模糊指代关键词
        reference_keywords = [
            "重试上面的问题", "重试上面这个问题", "重试这个问题",
            "上面的问题", "上面这个", "这个", "那个",
            "再试一次", "再来一次", "重新回答",
        ]
        
        # 检查是否是模糊指代
        for keyword in reference_keywords:
            if task_stripped == keyword or task_stripped.startswith(keyword):
                # 从历史中提取上一个用户问题
                import re
                user_messages = re.findall(r'用户[:：]\s*(.+?)(?:\n|$)', history_context)
                for msg in reversed(user_messages):
                    msg_stripped = msg.strip()
                    is_ref = any(kw in msg_stripped for kw in reference_keywords)
                    if not is_ref and len(msg_stripped) > 2:
                        return msg_stripped
                return task
        
        # 检查是否是简短回答（可能是回答追问）
        if len(task_stripped) <= 10:
            import re
            # 检查历史中是否有追问
            # 格式："请问您想了解哪个地方的天气？" 或 "请问您想查询哪个店铺？"
            clarify_patterns = [
                r'请问.*?哪个地方.*?天气',
                r'请问.*?哪里.*?天气',
                r'请问.*?哪个.*?店铺',
                r'请问.*?想了解.*?什么',
                r'请问.*?想查询.*?什么',
            ]
            
            for pattern in clarify_patterns:
                match = re.search(pattern, history_context)
                if match:
                    # 根据追问类型组合完整问题
                    clarify_text = match.group(0)
                    
                    if '天气' in clarify_text:
                        return f"{task_stripped}天气怎么样？"
                    elif '店铺' in clarify_text:
                        return f"{task_stripped}店铺的信息"
                    else:
                        return f"{task_stripped}的相关信息"
        
        return task
    
    async def _check_need_clarification(self, question: str, shop_name: str = "", history_context: str = "") -> dict:
        """
        检查是否需要追问

        Args:
            question: 用户问题
            shop_name: 店铺名称（有店铺则不追问店铺相关）

        Returns:
            {"need_clarify": bool, "reason": str, "missing_info": str}
        """
        try:
            question_stripped = question.strip()

            # 规则判断：助手自身问题不需要追问
            about_keywords = [
                "你是谁", "你叫什么", "你的名字", "自我介绍", "介绍自己",
                "你能做什么", "你的功能", "你的能力", "怎么用", "使用方法",
                "你是", "关于你", "助手", "帮手",
                "支持什么", "支持哪些", "还支持", "有哪些功能", "功能介绍",
                "能帮我做什么", "能干什么", "可以做什么", "有什么用",
                "你会什么", "你会做什么", "都可以做", "操作功能",
            ]
            if any(kw in question_stripped for kw in about_keywords):
                print(f"[RAGAgent] 助手自身问题，跳过追问: {question}")
                return {"need_clarify": False, "reason": "", "missing_info": ""}

            # 模糊指代判断交给 LLM（带上下文），不硬编码规则

            # 有店铺上下文时，跳过店铺相关追问
            if shop_name:
                shop_internal_keywords = [
                    "营业", "开门", "关门", "下班", "打烊", "几点",
                    "套餐", "价格", "退款", "库存", "物料", "员工", "排班",
                    "营业额", "收入", "支出", "顾客", "会员",
                ]
                if any(kw in question_stripped for kw in shop_internal_keywords):
                    print(f"[RAGAgent] 店铺内部问题，跳过追问: {question}")
                    return {"need_clarify": False, "reason": "", "missing_info": ""}
            
            # LLM 判断
            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage
            from app.utils.json_parser import safe_parse_json
            
            llm = get_chat_llm(temperature=0)
            
            context_info = f"\n用户店铺：{shop_name}" if shop_name else ""
            history_section = ""
            if history_context:
                history_section = f"""

【历史对话】
{history_context}

注意：当用户的问题是省略句或模糊指代时，结合历史对话理解用户的真实意图。
例如：历史中用户问过天气，当前问"海宁呢？"，说明用户想查海宁天气，不需要追问。"""
            
            prompt = f"""判断用户问题是否需要追问才能准确回答。
{context_info}{history_section}

用户问题："{question}"

判断规则（必须严格遵守）：

## 需要追问的情况
1. 问题缺少关键信息且历史对话中也找不到（如"查一下那个顾客"但没有上下文）
2. 问题有多种理解方式且无法从上下文判断

## 不需要追问的情况（优先级更高）
1. 历史对话中已经提供了足够信息，可以推断出用户意图
2. "重试"、"上面那个"、"之前的问题" 等模糊指代 → 结合历史对话理解，不要追问
3. 问题已经很明确（如"本月营业额"）
4. 问题涉及店铺内部数据
5. 用户在问关于助手自身的问题
6. 用户在问通用知识问题

## 重要
- 当问题是模糊指代时，必须先查看【历史对话】，看能否解析出用户的真实意图
- 只有当历史对话中也找不到相关信息时，才需要追问
- 宁可猜错也不要追问太多次

只返回 JSON 格式：
{{"need_clarify": true/false, "reason": "原因", "missing_info": "缺少的信息"}}"""
            
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result = safe_parse_json(response.content.strip())
            
            if result and isinstance(result, dict):
                result["clarify_message"] = self._generate_clarification_message(question, result.get("missing_info", ""))
                result["quick_questions"] = [
                    "今天营业额多少？",
                    "本月经营情况如何？",
                    "有哪些套餐？",
                    "库存还有多少？"
                ]
                return result
            
            return {"need_clarify": False, "reason": "", "missing_info": ""}
        except Exception as e:
            print(f"[RAGAgent] 追问检查失败: {str(e)}")
            return {"need_clarify": False, "reason": "", "missing_info": ""}
    
    def _generate_clarification_message(self, question: str, missing_info: str) -> str:
        """
        生成追问消息（根据问题上下文）
        
        Args:
            question: 用户问题
            missing_info: 缺少的信息
        
        Returns:
            追问消息
        """
        question_lower = question.lower()
        
        # 根据问题类型和缺少的信息生成追问
        if "地点" in missing_info or "位置" in missing_info:
            # 判断问题类型
            if any(kw in question_lower for kw in ["天气", "气温", "下雨"]):
                return "请问您想了解哪个地方的天气？"
            elif any(kw in question_lower for kw in ["关门", "营业", "开门", "打烊", "下班"]):
                return "请问您想查询哪个店铺的营业状态？"
            else:
                return f"请问您想了解哪个地方的信息？"
        elif "套餐" in missing_info:
            return "请问您想了解哪个套餐？我们有单次体验、周卡、月卡等。"
        elif "时间" in missing_info:
            return "请问您想了解哪个时间段的数据？例如：今天、本周、本月等。"
        elif "店铺" in missing_info or "对象" in missing_info:
            return "请问您想查询哪个店铺的信息？"
        else:
            return f"为了更准确地回答您的问题，请补充以下信息：{missing_info}"
    
    async def _review_content(self, question: str, answer: str) -> dict:
        """评审内容是否与用户问题相关"""
        try:
            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage
            
            llm = get_chat_llm(temperature=0)
            prompt = CONTENT_REVIEW_PROMPT.format(question=question, answer=answer[:1000])
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            content = response.content.strip()
            result = safe_parse_json(content)
            
            if result and isinstance(result, dict):
                return result
            
            return {"is_relevant": True, "reason": "评审解析失败", "suggestion": ""}
        except Exception as e:
            print(f"[RAGAgent] 内容评审失败: {str(e)}")
            return {"is_relevant": True, "reason": "评审失败", "suggestion": ""}
    
    async def _check_llm_can_answer(self, question: str, history_context: str = "") -> bool:
        """让 LLM 判断是否可以用通用知识回答"""
        try:
            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage
            
            llm = get_chat_llm(temperature=0)
            
            prompt = f"""判断以下问题是否可以用通用知识回答（不需要查询特定数据库或搜索互联网）。

用户问题：{question}

判断标准：
1. 如果是关于定义、概念、方法论、最佳实践等通用知识 → 可以回答
2. 如果是关于特定店铺的数据（如"今天营业额多少"）→ 无法回答
3. 如果是实时信息（如"今天天气"）→ 无法回答
4. 如果是通用商业建议（如"如何提高顾客满意度"）→ 可以回答

只返回 JSON 格式：
{{"can_answer": true/false, "reason": "判断原因"}}"""
            
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            content = response.content.strip()
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()

            result = json.loads(content)
            can_answer = result.get("can_answer", False)
            reason = result.get("reason", "")
            
            print(f"[RAGAgent] LLM 判断: can_answer={can_answer}, reason={reason}")
            return can_answer
        except Exception as e:
            print(f"[RAGAgent] LLM 判断失败: {str(e)}")
            return False
    
    async def _generate_llm_answer(self, question: str, history_context: str = "") -> str:
        """让 LLM 用通用知识回答（只返回知识内容，不包含角色/安全/合规）"""
        try:
            from app.llm import get_chat_llm
            from langchain_core.messages import SystemMessage, HumanMessage
            from datetime import datetime

            llm = get_chat_llm()
            current_date = datetime.now().strftime("%Y年%m月%d日")

            system_prompt = f"""你是一个知识检索助手。根据提供的上下文信息，返回相关的知识内容。

当前日期：{current_date}

规则：
1. 只基于提供的上下文信息回答，不要生成上下文之外的内容
2. 【绝对禁止编造】不要编造任何数据、功能、政策或信息。如果上下文中没有相关信息，直接回答"知识库中暂无相关信息"
3. 不要编造不存在的功能或能力。例如，如果上下文没有提到"营销支持"，就不要说有这个功能
4. 返回的内容将由另一个系统进行汇总和格式化
5. 不要添加角色扮演内容"""

            user_message = question
            if history_context:
                user_message = f"""【历史对话】
{history_context}

【当前问题】
{question}"""

            response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message)
            ])

            return response.content
        except Exception as e:
            print(f"[RAGAgent] LLM 生成答案失败: {str(e)}")
            return ""
    
    async def _search_web(self, query: str, context: UserContext) -> str:
        """搜索互联网获取实时信息（优化版：使用 LLM 优化搜索关键词）"""
        try:
            from app.search.tavily_client import web_search
            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage
            
            # 构建店铺上下文
            shop_context = ""
            if context and context.shop_name:
                shop_context = f"店铺名称：{context.shop_name}"
            
            # 优化搜索关键词
            llm = get_chat_llm(temperature=0)
            optimize_prompt = SEARCH_QUERY_OPTIMIZE_PROMPT.format(
                question=query,
                shop_context=shop_context
            )
            response = await llm.ainvoke([HumanMessage(content=optimize_prompt)])
            optimized_queries = [q.strip() for q in response.content.strip().split("\n") if q.strip()]
            
            # 使用优化后的关键词搜索
            all_results = []
            for opt_query in optimized_queries[:2]:
                if not opt_query:
                    continue
                
                print(f"[RAGAgent] 使用优化关键词搜索: {opt_query}")
                result = await web_search(
                    query=opt_query,
                    context="",
                    max_results=3,
                    language="zh",
                )
                if result and "搜索失败" not in result and len(result) > 50:
                    all_results.append(result)
            
            # 合并结果
            if all_results:
                return "\n\n".join(all_results)
            return ""
        except Exception as e:
            print(f"[RAGAgent] 互联网搜索失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return ""
    
    async def execute(self, task: str, context: UserContext, **kwargs) -> AgentResult:
        """
        执行 RAG 任务
        
        流程：
        1. 解析模糊指代（如"重试上面这个问题"）
        2. 实时性问题 → 直接搜索互联网
        3. 检索经验池 → 有结果则返回
        4. 检索知识库 → 有结果且置信度高则返回
        5. LLM 判断 → 可以用通用知识回答则返回
        6. 搜索互联网 → 返回结果
        """
        print(f"[RAGAgent] 开始执行任务: {task}")
        experience_pool = get_experience_pool()
        
        # 获取上下文
        history_context = kwargs.get("history_context", "")
        route_context = kwargs.get("route_context", "")
        
        # 解析模糊指代（如"重试上面这个问题"）
        actual_task = self._resolve_reference(task, history_context)
        if actual_task != task:
            print(f"[RAGAgent] 解析模糊指代: '{task}' -> '{actual_task}'")
            task = actual_task
        
        try:
            # 0. 检查是否需要追问（使用原始问题，传入历史上下文）
            shop_name = context.shop_name if context else ""
            original_question = kwargs.get("original_question", task)
            clarification = await self._check_need_clarification(original_question, shop_name, history_context)
            if clarification.get("need_clarify"):
                missing_info = clarification.get("missing_info", "")
                print(f"[RAGAgent] 需要追问，缺少信息: {missing_info}")
                
                # 生成追问消息
                clarify_msg = self._generate_clarification_message(task, missing_info)
                
                return AgentResult(
                    agent=AgentType.RAG,
                    result=clarify_msg,
                    confidence=0.5,
                    metadata={"need_clarification": True, "missing_info": missing_info}
                )
            
            # 判断是否需要互联网搜索（LLM 判断，替代关键词匹配）
            need_search = await self._should_search_web(original_question, task, history_context)

            # 1. 需要搜索互联网
            if need_search:
                print(f"[RAGAgent] LLM 判断需要互联网搜索")
                web_result = await self._search_web(task, context)
                
                if web_result and "搜索失败" not in web_result and len(web_result) > 50:
                    return AgentResult(
                        agent=AgentType.RAG,
                        result=web_result,
                        confidence=0.7,
                        metadata={"source": "web_search", "is_realtime": True}
                    )
                else:
                    return AgentResult(
                        agent=AgentType.RAG,
                        result="抱歉，暂时无法获取实时信息，请稍后重试。",
                        confidence=0.3,
                        success=False,
                        error="Web search failed"
                    )
            
            # 2. 检索经验池（非实时性查询）
            similar_exps = await experience_pool.retrieve_similar("rag", task, k=2)
            for exp in similar_exps:
                if exp.experience_type == "success" and exp.quality_score >= 80 and exp.solution and len(exp.solution.strip()) > 10:
                    print(f"[RAGAgent] 从经验池获取答案: {exp.id}")
                    return AgentResult(
                        agent=AgentType.RAG,
                        result=exp.solution,
                        confidence=0.9,
                        metadata={"from_experience": True, "experience_id": exp.id}
                    )
            
            # 3. 检索知识库
            from app.rag.agentic_rag import get_agentic_rag
            agentic_rag = get_agentic_rag()
            
            # 构建增强的任务描述
            enhanced_task = task
            if route_context:
                enhanced_task = f"""【Router 分析结果】
{route_context}

【用户原始问题】
{task}"""
            if history_context:
                enhanced_task = f"""【历史对话】
{history_context}

{enhanced_task}"""
            
            result = await asyncio.to_thread(
                agentic_rag.query,
                question=enhanced_task,
                shop_id=context.shop_id,
            )
            
            answer = result.get("answer", "")
            confidence = result.get("confidence", 0.8)
            
            # 修正置信度
            if not answer or len(answer.strip()) < 10:
                confidence = 0.0
                print(f"[RAGAgent] 知识库答案为空或太短，修正置信度为 0")
            
            print(f"[RAGAgent] 知识库返回: 置信度={confidence}, 答案长度={len(answer)}")
            
            # 4. 知识库有结果且置信度高，直接返回
            if confidence >= 0.6 and answer and len(answer.strip()) > 10:
                print(f"[RAGAgent] 知识库答案置信度高，直接返回")
                return AgentResult(
                    agent=AgentType.RAG,
                    result=answer,
                    confidence=confidence,
                    metadata={"source": "knowledge_base"}
                )
            
            # 5. 知识库无结果或置信度低，让 LLM 判断是否可以用通用知识回答
            print(f"[RAGAgent] 知识库无结果，让 LLM 判断是否可以用通用知识回答")
            llm_can_answer = await self._check_llm_can_answer(task, history_context)
            
            if llm_can_answer:
                print(f"[RAGAgent] LLM 可以用通用知识回答")
                llm_answer = await self._generate_llm_answer(task, history_context)
                if llm_answer and len(llm_answer.strip()) > 10:
                    return AgentResult(
                        agent=AgentType.RAG,
                        result=llm_answer,
                        confidence=0.7,
                        metadata={"source": "llm_general_knowledge"}
                    )
            
            # 6. LLM 也无法回答，搜索互联网
            print(f"[RAGAgent] LLM 无法回答，搜索互联网")
            web_result = await self._search_web(task, context)
            
            if web_result and "搜索失败" not in web_result and len(web_result) > 50:
                # 评审搜索结果
                review = await self._review_content(task, web_result)
                if review.get("is_relevant"):
                    return AgentResult(
                        agent=AgentType.RAG,
                        result=web_result,
                        confidence=0.7,
                        metadata={"source": "web_search"}
                    )
            
            # 7. 所有方法都失败
            return AgentResult(
                agent=AgentType.RAG,
                result="抱歉，暂时无法获取相关信息，请稍后重试。",
                confidence=0.3,
                success=False,
                error="All methods failed"
            )
        except Exception as e:
            print(f"[RAGAgent] 执行失败: {str(e)}")
            
            # 记录失败案例
            await experience_pool.record_failure_and_fix(
                agent_type="rag",
                question=task,
                error=str(e),
                original_solution="",
            )
            
            return AgentResult(
                agent=AgentType.RAG,
                result=f"知识问答失败: {str(e)}",
                confidence=0.0,
                success=False,
                error=str(e)
            )


# 全局实例
_rag_agent = None


def get_rag_agent() -> RAGAgent:
    """获取 RAG Agent 单例"""
    global _rag_agent
    if _rag_agent is None:
        _rag_agent = RAGAgent()
    return _rag_agent
