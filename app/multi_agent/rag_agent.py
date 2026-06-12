"""
RAG Agent - 知识问答 Agent
调用现有 RAG 模块进行知识问答
集成经验池学习
集成互联网搜索（实时信息）
集成内容评审（检查输出是否符合用户问题）
"""

import asyncio
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


class RAGAgent:
    """
    RAG Agent - 知识问答
    
    功能：
    - 回答关于套餐、价格、营业时间等问题
    - 查询店铺规则、政策等信息
    - 集成经验池学习
    - 集成互联网搜索（实时信息）
    - 集成内容评审
    """
    
    # 需要实时信息的关键词
    REALTIME_KEYWORDS = [
        "今天", "今日", "昨天", "本周", "本月", "最近", "现在", "当前",
        "新闻", "天气", "股票", "汇率", "价格", "优惠", "活动",
        "最新", "实时", "热点", "趋势", "排行",
    ]
    
    def _is_realtime_query(self, query: str) -> bool:
        """
        判断是否需要实时信息
        
        Args:
            query: 用户查询
        
        Returns:
            是否需要实时信息
        """
        return any(keyword in query for keyword in self.REALTIME_KEYWORDS)
    
    async def _review_content(self, question: str, answer: str) -> dict:
        """
        评审内容是否与用户问题相关
        
        Args:
            question: 用户问题
            answer: AI回答
        
        Returns:
            评审结果 {"is_relevant": bool, "reason": str, "suggestion": str}
        """
        try:
            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage
            
            llm = get_chat_llm(temperature=0)
            prompt = CONTENT_REVIEW_PROMPT.format(question=question, answer=answer[:1000])
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            
            # 解析 JSON
            content = response.content.strip()
            result = safe_parse_json(content)
            
            if result and isinstance(result, dict):
                return result
            
            # 解析失败时默认通过
            print(f"[RAGAgent] 内容评审 JSON 解析失败，默认通过")
            return {"is_relevant": True, "reason": "评审解析失败", "suggestion": ""}
        except Exception as e:
            print(f"[RAGAgent] 内容评审失败: {str(e)}")
            return {"is_relevant": True, "reason": "评审失败", "suggestion": ""}
    
    async def _search_web(self, query: str, context: UserContext) -> str:
        """
        搜索互联网获取实时信息（优化版：使用 LLM 优化搜索关键词）
        
        Args:
            query: 搜索查询
            context: 用户上下文
        
        Returns:
            搜索结果
        """
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
            for opt_query in optimized_queries[:2]:  # 最多使用 2 个关键词
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
        
        Args:
            task: 用户任务
            context: 用户上下文
            **kwargs: 额外参数
                - history_context: 历史上下文
                - route_context: 路由分析结果
        
        Returns:
            执行结果
        """
        print(f"[RAGAgent] 开始执行任务: {task}")
        experience_pool = get_experience_pool()
        
        # 获取历史上下文
        history_context = kwargs.get("history_context", "")
        
        # 获取路由上下文（Router 的分析结果）
        route_context = kwargs.get("route_context", "")
        
        try:
            # 判断是否是实时性查询
            is_realtime = self._is_realtime_query(task)
            
            # 1. 检索经验池（实时性查询跳过）
            if not is_realtime:
                similar_exps = await experience_pool.retrieve_similar("rag", task, k=2)
                
                # 2. 如果有高质量的成功案例，直接返回（必须有内容）
                for exp in similar_exps:
                    if exp.experience_type == "success" and exp.quality_score >= 80 and exp.solution and len(exp.solution.strip()) > 10:
                        print(f"[RAGAgent] 从经验池获取答案: {exp.id}")
                        return AgentResult(
                            agent=AgentType.RAG,
                            result=exp.solution,
                            confidence=0.9,
                            metadata={"from_experience": True, "experience_id": exp.id}
                        )
            else:
                print(f"[RAGAgent] 实时性查询，跳过经验池检索")
            
            # 3. 调用现有 RAG 模块（传递历史上下文和路由上下文）
            from app.rag.agentic_rag import get_agentic_rag
            
            agentic_rag = get_agentic_rag()
            
            # 构建增强的任务描述
            enhanced_task = task
            
            # 添加路由上下文（Router 的分析结果）
            if route_context:
                enhanced_task = f"""【Router 分析结果】
{route_context}

【用户原始问题】
{task}"""
            
            # 添加历史上下文
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
            
            # 修正置信度：如果答案为空或太短，置信度应该很低
            if not answer or len(answer.strip()) < 10:
                confidence = 0.0
                print(f"[RAGAgent] 知识库答案为空或太短，修正置信度为 0")
            
            print(f"[RAGAgent] 知识库返回: 置信度={confidence}, 答案长度={len(answer)}")
            
            # 4. 如果知识库答案置信度低或答案为空或需要实时信息，尝试搜索互联网
            need_web_search = confidence < 0.6 or is_realtime or not answer or len(answer.strip()) < 10
            
            print(f"[RAGAgent] 知识库置信度: {confidence}, 是否实时查询: {is_realtime}, 需要搜索: {need_web_search}")
            
            if need_web_search:
                print(f"[RAGAgent] 知识库答案置信度低或需要实时信息，尝试搜索互联网")
                
                # 最多重试 2 次
                max_search_retries = 2
                search_success = False
                
                for search_attempt in range(max_search_retries):
                    web_result = await self._search_web(task, context)
                    
                    print(f"[RAGAgent] 第 {search_attempt + 1} 次搜索，结果长度: {len(web_result) if web_result else 0}")
                    
                    if web_result and "搜索失败" not in web_result and len(web_result) > 50:
                        # 搜索成功，评审内容是否与用户问题相关
                        review = await self._review_content(task, web_result)
                        
                        if review.get("is_relevant"):
                            # 内容相关，使用搜索结果
                            answer = web_result
                            confidence = 0.7
                            search_success = True
                            print(f"[RAGAgent] 第 {search_attempt + 1} 次搜索结果相关")
                            break
                        else:
                            # 内容不相关，继续重试
                            print(f"[RAGAgent] 第 {search_attempt + 1} 次搜索结果不相关: {review.get('reason')}")
                            if search_attempt < max_search_retries - 1:
                                print(f"[RAGAgent] 准备重试搜索...")
                    else:
                        print(f"[RAGAgent] 搜索结果为空或失败")
                        break
                
                # 所有重试都失败
                if not search_success:
                    if not answer or "未找到" in answer or "抱歉" in answer:
                        answer = "抱歉，暂时无法获取相关信息，请稍后重试。"
            
            # 5. 成功时记录到经验池（置信度足够高时，且非实时性查询，且答案非空）
            if confidence >= 0.6 and not is_realtime and answer and len(answer.strip()) > 10:
                # 构建解决流程
                solving_process = [
                    {"step": 1, "description": "知识库检索", "detail": f"检索知识库，置信度: {confidence:.2f}"},
                ]
                if need_web_search:
                    solving_process.append({"step": 2, "description": "互联网搜索", "detail": "搜索实时信息"})
                    solving_process.append({"step": 3, "description": "内容评审", "detail": "评审搜索结果相关性"})
                
                await experience_pool.record_success(
                    agent_type="rag",
                    question=task,
                    solution=answer,
                    result_summary=answer[:200],
                    solving_process=solving_process,
                )
            
            return AgentResult(
                agent=AgentType.RAG,
                result=answer,
                confidence=confidence,
                metadata={
                    "sources": result.get("sources", []),
                    "intent": result.get("intent", ""),
                    "web_searched": need_web_search,
                }
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
