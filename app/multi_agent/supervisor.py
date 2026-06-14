"""
Supervisor Agent - 任务调度器
负责任务分析、Agent 调度、结果汇总
支持任务拆分，将复杂任务拆分成多个子任务
支持串行/并行混合执行
集成经验池学习
"""

import time
import asyncio
import json
from typing import Dict, Any, List, Optional
from app.llm import get_chat_llm
from app.common.user_context import UserContext
from app.multi_agent.protocol import (
    AgentResult, TaskPlan, MultiAgentState, SubTask,
    AgentType, TaskComplexity
)
from app.multi_agent.router import get_task_router
from app.multi_agent.rag_agent import RAGAgent
from app.multi_agent.nl2sql_agent import NL2SQLAgent
from app.multi_agent.tool_agent import ToolAgent
from app.multi_agent.vision_agent import VisionAgent
from app.multi_agent.llm_agent import LLMAgent
from monitoring.langfuse_config import create_trace, create_span
from app.experience.pool import get_experience_pool
from app.utils.json_parser import safe_parse_json


# 结果汇总提示词
SUMMARIZE_PROMPT = """你是一个专业的店铺智能助手，负责帮助店主分析经营数据、提供运营建议。

当前日期：{current_date}

用户问题：{task}

可用信息：
{results}

要求：
1. **身份定位**：你是店铺智能助手，不要提及你是AI模型或使用模型名称（如MiMo、GPT等）
2. **直接回答用户问题**，不要提及执行过程、子任务等内部概念
3. **只使用有效的信息**，忽略错误和失败的内容
4. **使用当前实际日期**（{current_date}），不要使用其他日期
5. **如果信息不足，基于通用商业知识补充**，但必须：
   - 符合中国法律法规和商业道德
   - 明确标注"基于通用经验"或"一般建议"
   - 不要编造具体数据或虚假案例
6. 使用友好、专业的语气回答
7. 支持 Markdown 格式（表格、列表等）
8. 如果完全没有可用信息，诚实说明并给出建议

回答："""


REVIEW_PROMPT = """评审以下回答是否满足用户需求。

用户问题：{task}

AI回答：
{result}

评审标准：
1. 回答是否直接解决了用户的问题？
2. 是否包含不应该展示给用户的内容（错误信息、内部执行过程）？
3. 回答是否完整、专业、有价值？
4. 是否有胡编乱造的内容？

请返回 JSON 格式：
{{
    "passed": true/false,
    "score": 0-100,
    "issues": ["问题1", "问题2"],
    "suggestion": "改进建议"
}}"""


class SupervisorAgent:
    """
    Supervisor Agent - 任务调度器
    
    职责：
    1. 分析用户任务类型
    2. 拆分复杂任务为多个子任务
    3. 分配子任务给合适的 Agent
    4. 支持串行/并行混合执行
    5. 汇总多个子任务的结果
    """
    
    def __init__(self):
        self.router = get_task_router()
        self.agents = {
            AgentType.RAG: RAGAgent(),
            AgentType.NL2SQL: NL2SQLAgent(),
            AgentType.TOOL: ToolAgent(),
            AgentType.VISION: VisionAgent(),
            AgentType.LLM: LLMAgent(),  # 新增：LLM 总结分析
        }
        self._llm = None
        self._progress_callback = None  # 进度回调函数
    
    @property
    def llm(self):
        """懒加载 LLM"""
        if self._llm is None:
            self._llm = get_chat_llm()
        return self._llm
    
    def set_progress_callback(self, callback):
        """设置进度回调函数"""
        self._progress_callback = callback
    
    async def _notify_progress(self, step: str, content: str, status: str = "processing"):
        """通知进度"""
        if self._progress_callback:
            await self._progress_callback(step, content, status)
    
    async def execute(self, task: str, context: UserContext, image_url: str = None, history_context: str = "") -> AgentResult:
        """
        执行任务（带评审和重试机制，集成经验池）
        
        Args:
            task: 用户任务
            context: 用户上下文
            image_url: 图像 URL（可选）
            history_context: 历史上下文（纪要 + 最近对话）
        
        Returns:
            执行结果
        """
        # 创建追踪
        trace = create_trace("multi_agent", {
            "task": task,
            "user_id": context.user_id,
            "shop_id": context.shop_id,
            "role": context.role,
        })
        start_time = time.time()
        max_retries = 3
        attempt = 0  # 初始化循环变量
        experience_pool = get_experience_pool()
        
        # 保存历史上下文，供子任务使用
        self._current_history_context = history_context
        self._current_route_context = ""
        
        try:
            # 0. 检索经验池
            similar_exps = await experience_pool.retrieve_similar("supervisor", task, k=2)
            
            # 如果有高质量的成功案例，直接返回
            for exp in similar_exps:
                if exp.experience_type == "success" and exp.quality_score >= 85:
                    print(f"[Supervisor] 从经验池获取答案: {exp.id}")
                    return AgentResult(
                        agent=AgentType.SUPERVISOR,
                        result=exp.solution,
                        confidence=0.9,
                        metadata={"from_experience": True, "experience_id": exp.id}
                    )
            
            # 如果有历史上下文，将其添加到任务前面
            full_task = task
            if history_context:
                full_task = f"""【对话历史】
{history_context}

【当前任务】
{task}"""
            
            last_result = None
            last_review = None
            best_result = None      # 最高分数的结果
            best_score = 0          # 最高分数
            best_review = None      # 最高分数的评审
            
            for attempt in range(max_retries):
                # 1. 创建任务计划（传递历史上下文）
                plan = await self.router.create_plan(full_task, has_image=bool(image_url), shop_context=history_context)
                
                # 输出任务拆分结果
                if plan.sub_tasks:
                    await self._notify_progress("任务拆分", f"已拆分为 {len(plan.sub_tasks)} 个子任务")
                
                # 记录任务计划
                if trace:
                    create_span(trace, f"task_plan_attempt_{attempt + 1}", {
                        "complexity": plan.complexity,
                        "agents": plan.agents,
                        "sub_tasks_count": len(plan.sub_tasks),
                    })
                
                # 2. 根据复杂度执行
                if plan.complexity == TaskComplexity.SIMPLE:
                    result = await self._execute_single(full_task, plan.agents[0], context, image_url, trace)
                else:
                    result = await self._execute_sub_tasks(full_task, plan, context, image_url, trace)
                
                last_result = result
                
                # 3. 评审结果
                if result.success and result.result:
                    await self._notify_progress("结果汇总", "正在汇总分析结果...")
                    review = await self._review_result(task, result.result)
                    last_review = review
                    score = review.get("score", 0)
                    
                    # 记录最高分数的结果
                    if score > best_score:
                        best_score = score
                        best_result = result
                        best_review = review
                    
                    if review.get("passed") and score >= 70:
                        # 评审通过
                        print(f"[Supervisor] 第 {attempt + 1} 次执行通过评审，分数: {score}")
                        await self._notify_progress("完成", "处理完成", "success")
                        break
                    else:
                        print(f"[Supervisor] 第 {attempt + 1} 次执行未通过评审，分数: {score}，问题: {review.get('issues')}")
                        await self._notify_progress("评审", f"质量评分: {score}/100，正在优化...", "warning")
                        if attempt < max_retries - 1:
                            # 调整任务描述，提示上次的问题
                            full_task = f"{task}\n\n注意：上次回答有以下问题，请改进：{', '.join(review.get('issues', []))}"
                else:
                    # 执行失败，不需要评审
                    print(f"[Supervisor] 第 {attempt + 1} 次执行失败: {result.error}")
                    if attempt < max_retries - 1:
                        # 尝试简化任务
                        full_task = f"{task}\n\n注意：请简化处理，确保能给出有效回答"
            
            # 计算执行时间
            duration_ms = (time.time() - start_time) * 1000
            
            # 使用最高分数的结果（而不是最后一次）
            final_result = best_result if best_result else last_result
            final_review = best_review if best_review else last_review
            
            # 评审未通过但有结果时，返回成功但标注质量分数
            if final_review and not final_review.get("passed") and final_result and final_result.success:
                # 添加质量提示到结果开头
                quality_note = f"⚠️ 以下回答可能不够完善（质量评分：{final_review.get('score', 0)}/100）\n\n"
                final_result.result = quality_note + final_result.result
                final_result.confidence = 0.5  # 降低置信度
                final_result.duration_ms = duration_ms
                final_result.metadata = final_result.metadata or {}
                final_result.metadata["quality_score"] = final_review.get("score", 0)
                final_result.metadata["quality_issues"] = final_review.get("issues", [])
                
                print(f"[Supervisor] 评审未通过但返回最佳结果，质量分数: {final_review.get('score')}")
                
                if trace:
                    create_span(trace, "supervisor_result", {
                        "success": True,
                        "duration_ms": duration_ms,
                        "attempts": attempt + 1,
                        "quality_score": final_review.get("score"),
                        "best_score": best_score,
                    })
                
                return final_result
            
            # 连续 3 次都执行失败
            if final_result and not final_result.success:
                return AgentResult(
                    agent=AgentType.SUPERVISOR,
                    result="抱歉，处理过程中出现问题，请稍后重试或换个方式提问。",
                    confidence=0.3,
                    success=False,
                    error="All attempts failed",
                    duration_ms=duration_ms
                )
            
            # 正常返回结果
            if final_result:
                final_result.duration_ms = duration_ms
                
                # 成功时记录到经验池
                if last_result.success and last_result.result:
                    # 构建解决流程
                    solving_process = [
                        {"step": 1, "description": "任务分析", "detail": "分析问题类型和复杂度"},
                        {"step": 2, "description": "任务拆分", "detail": "拆分为多个子任务"},
                        {"step": 3, "description": "执行子任务", "detail": f"执行 {len(plan.sub_tasks)} 个子任务"},
                        {"step": 4, "description": "结果汇总", "detail": "汇总并生成最终答案"},
                    ]
                    
                    await experience_pool.record_success(
                        agent_type="supervisor",
                        question=task,
                        solution=last_result.result,
                        result_summary=last_result.result[:200],
                        solving_process=solving_process,
                    )
            
            # 记录最终结果
            if trace:
                create_span(trace, "supervisor_result", {
                    "success": last_result.success if last_result else False,
                    "duration_ms": duration_ms,
                    "attempts": attempt + 1,
                })
            
            return last_result or AgentResult(
                agent=AgentType.SUPERVISOR,
                result="执行失败，请稍后重试",
                confidence=0.0,
                success=False,
                error="No result"
            )
            
        except Exception as e:
            print(f"[Supervisor] 执行失败: {str(e)}")
            
            # 记录错误
            if trace:
                create_span(trace, "supervisor_error", {"error": str(e)})
            
            return AgentResult(
                agent=AgentType.SUPERVISOR,
                result=f"执行失败: {str(e)}",
                confidence=0.0,
                success=False,
                error=str(e)
            )
    
    async def _review_result(self, task: str, result: str) -> dict:
        """
        评审执行结果是否满足用户需求
        
        Args:
            task: 用户任务
            result: 执行结果
        
        Returns:
            评审结果 {"passed": bool, "score": int, "issues": list, "suggestion": str}
        """
        try:
            from langchain_core.messages import HumanMessage
            
            prompt = REVIEW_PROMPT.format(task=task, result=result[:2000])  # 限制长度
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            
            # 解析 JSON
            content = response.content.strip()
            result = safe_parse_json(content)
            
            if result and isinstance(result, dict):
                return result
            
            # 解析失败时默认通过
            print(f"[Supervisor] 评审 JSON 解析失败，默认通过")
            return {"passed": True, "score": 70, "issues": [], "suggestion": ""}
        except Exception as e:
            print(f"[Supervisor] 评审失败: {str(e)}")
            # 评审失败时默认通过
            return {"passed": True, "score": 70, "issues": [], "suggestion": ""}
            # 评审失败时默认通过
            return {"passed": True, "score": 70, "issues": [], "suggestion": ""}
    
    async def _execute_single(self, task: str, agent_type: str, context: UserContext, image_url: str = None, trace=None) -> AgentResult:
        """执行单个 Agent 任务"""
        agent = self.agents.get(agent_type)
        if not agent:
            return AgentResult(
                agent=agent_type,
                result=f"未知的 Agent 类型: {agent_type}",
                confidence=0.0,
                success=False,
                error=f"Unknown agent type: {agent_type}"
            )
        
        # 记录 Agent 执行
        if trace:
            create_span(trace, f"agent_{agent_type}_start", {"task": task[:100]})
        
        result = await agent.execute(task, context, image_url=image_url)
        
        # 记录 Agent 结果
        if trace:
            create_span(trace, f"agent_{agent_type}_result", {
                "confidence": result.confidence,
                "success": result.success,
                "result_length": len(result.result) if result.result else 0,
            })
        
        return result
    
    async def _execute_sub_tasks(
        self, 
        task: str, 
        plan: TaskPlan, 
        context: UserContext, 
        image_url: str = None, 
        trace=None
    ) -> AgentResult:
        """
        执行子任务（支持串行/并行混合执行）
        
        Args:
            task: 原始任务
            plan: 任务计划
            context: 用户上下文
            image_url: 图像 URL
            trace: LangFuse 追踪
        
        Returns:
            执行结果
        """
        # 记录子任务开始
        if trace:
            create_span(trace, "sub_tasks_start", {
                "sub_tasks_count": len(plan.sub_tasks),
                "sub_tasks": [sub_task.to_dict() for sub_task in plan.sub_tasks],
                "parallel": plan.parallel,
            })
        
        # 判断执行方式
        has_dependencies = any(sub_task.depends_on for sub_task in plan.sub_tasks)
        
        if has_dependencies:
            # 有依赖关系，串行执行
            print(f"[Supervisor] 检测到依赖关系，使用串行执行")
            result = await self._execute_sub_tasks_serial(task, plan.sub_tasks, context, image_url, trace)
        else:
            # 无依赖关系，并行执行
            print(f"[Supervisor] 无依赖关系，使用并行执行")
            result = await self._execute_sub_tasks_parallel(task, plan.sub_tasks, context, image_url, trace)
        
        return result
    
    async def _execute_sub_tasks_parallel(
        self, 
        task: str, 
        sub_tasks: List[SubTask], 
        context: UserContext, 
        image_url: str = None, 
        trace=None
    ) -> AgentResult:
        """
        并行执行子任务
        
        Args:
            task: 原始任务
            sub_tasks: 子任务列表
            context: 用户上下文
            image_url: 图像 URL
            trace: LangFuse 追踪
        
        Returns:
            执行结果
        """
        # 并行执行所有子任务
        sub_task_coroutines = []
        for sub_task in sub_tasks:
            sub_task_coroutines.append(
                self._execute_single_sub_task(sub_task, context, image_url, trace)
            )
        
        # 等待所有子任务完成
        sub_task_results = await asyncio.gather(*sub_task_coroutines, return_exceptions=True)
        
        # 处理子任务结果
        valid_results = []
        for i, result in enumerate(sub_task_results):
            if isinstance(result, AgentResult):
                # 将结果关联到子任务
                sub_tasks[i].result = result
                valid_results.append(result)
            elif isinstance(result, Exception):
                print(f"[Supervisor] 子任务 {i+1} 执行异常: {str(result)}")
                # 创建失败结果
                error_result = AgentResult(
                    agent=sub_tasks[i].agent,
                    result=f"子任务执行失败: {str(result)}",
                    confidence=0.0,
                    success=False,
                    error=str(result)
                )
                sub_tasks[i].result = error_result
                valid_results.append(error_result)
        
        # 记录子任务结果
        if trace:
            for i, result in enumerate(valid_results):
                create_span(trace, f"sub_task_{i+1}_result", {
                    "agent": result.agent,
                    "success": result.success,
                    "confidence": result.confidence,
                })
        
        # 汇总结果
        return await self._build_final_result(task, sub_tasks, valid_results, context, trace)
    
    async def _execute_sub_tasks_serial(
        self, 
        task: str, 
        sub_tasks: List[SubTask], 
        context: UserContext, 
        image_url: str = None, 
        trace=None
    ) -> AgentResult:
        """
        串行执行子任务（支持依赖关系和重试）
        
        Args:
            task: 原始任务
            sub_tasks: 子任务列表
            context: 用户上下文
            image_url: 图像 URL
            trace: LangFuse 追踪
        
        Returns:
            执行结果
        """
        # 按照拓扑排序执行子任务
        completed = {}  # 已完成的子任务 {id: result}
        valid_results = []
        max_retries = 2  # 每个子任务最多重试 2 次
        
        # 按 ID 排序
        sorted_sub_tasks = sorted(sub_tasks, key=lambda st: st.id)
        
        for sub_task in sorted_sub_tasks:
            # 检查依赖是否满足
            dependencies_met = all(dep_id in completed for dep_id in sub_task.depends_on)
            
            if not dependencies_met:
                print(f"[Supervisor] 子任务 {sub_task.id} 依赖未满足，跳过")
                error_result = AgentResult(
                    agent=sub_task.agent,
                    result=f"依赖的子任务未完成: {sub_task.depends_on}",
                    confidence=0.0,
                    success=False,
                    error=f"Dependencies not met: {sub_task.depends_on}"
                )
                sub_task.result = error_result
                valid_results.append(error_result)
                continue
            
            # 构建子任务上下文（包含依赖任务的结果）
            sub_task_context = self._build_sub_task_context(sub_task, completed, context)
            
            # 执行子任务（带重试）
            result = None
            for attempt in range(max_retries + 1):
                # 输出子任务开始
                if attempt == 0:
                    await self._notify_progress(
                        f"步骤 {sub_task.id}/{len(sorted_sub_tasks)}", 
                        f"正在执行: {sub_task.description}"
                    )
                else:
                    await self._notify_progress(
                        f"步骤 {sub_task.id}/{len(sorted_sub_tasks)}", 
                        f"重试第 {attempt} 次: {sub_task.description}",
                        "warning"
                    )
                
                # 执行子任务（添加异常处理）
                print(f"[Supervisor] 执行子任务 {sub_task.id} (第 {attempt + 1} 次): {sub_task.task}")
                try:
                    result = await self._execute_single_sub_task(sub_task, sub_task_context, image_url, trace)
                except Exception as e:
                    print(f"[Supervisor] 子任务 {sub_task.id} 执行异常: {str(e)}")
                    result = AgentResult(
                        agent=sub_task.agent,
                        result=f"执行异常: {str(e)}",
                        confidence=0.0,
                        success=False,
                        error=str(e)
                    )
                
                # 如果成功，跳出重试循环
                if result.success:
                    break
                
                # 如果失败且还有重试次数，继续重试
                if attempt < max_retries:
                    print(f"[Supervisor] 子任务 {sub_task.id} 失败，准备重试 ({attempt + 1}/{max_retries})")
            
            # 记录结果
            sub_task.result = result
            completed[sub_task.id] = result
            valid_results.append(result)
            
            # 输出子任务结果
            if result.success:
                await self._notify_progress(
                    f"步骤 {sub_task.id}/{len(sorted_sub_tasks)}", 
                    f"✓ 完成: {sub_task.description}",
                    "success"
                )
            else:
                await self._notify_progress(
                    f"步骤 {sub_task.id}/{len(sorted_sub_tasks)}", 
                    f"✗ 失败: {sub_task.description}",
                    "error"
                )
            
            # 记录子任务结果
            if trace:
                create_span(trace, f"sub_task_{sub_task.id}_result", {
                    "success": result.success,
                    "confidence": result.confidence,
                    "result_length": len(result.result) if result.result else 0,
                })
            
            # 如果子任务失败，记录但继续执行
            if not result.success:
                print(f"[Supervisor] 子任务 {sub_task.id} 执行失败: {result.error}")
        
        # 汇总结果
        return await self._build_final_result(task, sub_tasks, valid_results, context, trace)
    
    def _build_sub_task_context(self, sub_task: SubTask, completed: Dict[int, AgentResult], base_context: UserContext) -> UserContext:
        """
        构建子任务上下文（包含依赖任务的结果）
        
        Args:
            sub_task: 当前子任务
            completed: 已完成的子任务结果
            base_context: 基础上下文
        
        Returns:
            包含依赖结果的上下文
        """
        # 收集依赖任务的结果
        dependency_results = []
        for dep_id in sub_task.depends_on:
            if dep_id in completed:
                dep_result = completed[dep_id]
                if dep_result.success:
                    dependency_results.append(dep_result.result)
        
        # 将依赖结果添加到任务描述中
        if dependency_results:
            enhanced_task = f"{sub_task.task}\n\n参考信息：\n" + "\n".join(dependency_results)
        else:
            enhanced_task = sub_task.task
        
        # 创建增强的上下文
        enhanced_context = UserContext(
            user_id=base_context.user_id,
            shop_id=base_context.shop_id,
            role=base_context.role,
            permissions=base_context.permissions,
            is_super_admin=base_context.is_super_admin,
            username=base_context.username,
            display_name=base_context.display_name,
        )
        
        return enhanced_context
    
    async def _execute_single_sub_task(
        self, 
        sub_task: SubTask, 
        context: UserContext, 
        image_url: str = None, 
        trace=None
    ) -> AgentResult:
        """
        执行单个子任务
        
        Args:
            sub_task: 子任务
            context: 用户上下文
            image_url: 图像 URL
            trace: LangFuse 追踪
        
        Returns:
            执行结果
        """
        agent = self.agents.get(sub_task.agent)
        if not agent:
            return AgentResult(
                agent=sub_task.agent,
                result=f"未知的 Agent 类型: {sub_task.agent}",
                confidence=0.0,
                success=False,
                error=f"Unknown agent type: {sub_task.agent}"
            )
        
        # 记录子任务开始
        if trace:
            create_span(trace, f"sub_task_{sub_task.id}_start", {
                "task": sub_task.task,
                "agent": sub_task.agent,
            })
        
        # 执行子任务（传递预定义查询参数和上下文）
        extra_kwargs = {}
        if sub_task.query:
            extra_kwargs["query"] = sub_task.query
        
        # 传递历史上下文和路由上下文
        if hasattr(self, '_current_history_context') and self._current_history_context:
            extra_kwargs["history_context"] = self._current_history_context
        if hasattr(self, '_current_route_context') and self._current_route_context:
            extra_kwargs["route_context"] = self._current_route_context
        
        result = await agent.execute(sub_task.task, context, image_url=image_url, **extra_kwargs)
        
        # 记录子任务结果
        if trace:
            create_span(trace, f"sub_task_{sub_task.id}_result", {
                "success": result.success,
                "confidence": result.confidence,
                "result_length": len(result.result) if result.result else 0,
            })
        
        return result
    
    async def _build_final_result(
        self,
        task: str,
        sub_tasks: List[SubTask],
        valid_results: List[AgentResult],
        context: UserContext = None,
        trace=None
    ) -> AgentResult:
        """
        构建最终结果（只收集原始结果，不汇总）

        汇总由 stream_handler._final_summarize 统一处理（带 system_prompts）

        Args:
            task: 原始任务
            sub_tasks: 子任务列表
            valid_results: 有效的执行结果
            context: 用户上下文
            trace: LangFuse 追踪

        Returns:
            最终执行结果（原始数据）
        """
        if valid_results:
            # 收集所有子任务的原始结果（不汇总）
            raw_results = []
            for sub_task in sub_tasks:
                agent_name = sub_task.agent.value if hasattr(sub_task.agent, 'value') else str(sub_task.agent or "unknown")
                if sub_task.result and sub_task.result.success and sub_task.result.result:
                    raw_results.append({
                        "action": sub_task.task,
                        "tool": agent_name,
                        "success": True,
                        "result": sub_task.result.result,
                        "error": "",
                    })
                elif sub_task.result:
                    raw_results.append({
                        "action": sub_task.task,
                        "tool": agent_name,
                        "success": False,
                        "result": "",
                        "error": sub_task.result.error or "执行失败",
                    })

            # 拼接原始结果文本（供 _final_summarize 使用）
            result_text = ""
            for i, r in enumerate(raw_results):
                status = "✓" if r["success"] else "✗"
                result_text += f"[{status}] {r['action']}\n"
                if r["success"] and r["result"]:
                    result_text += f"{r['result']}\n\n"
                elif r["error"]:
                    result_text += f"错误: {r['error']}\n\n"

            # 记录
            if trace:
                create_span(trace, "collect_results", {
                    "sub_tasks_count": len(sub_tasks),
                    "success_count": sum(1 for r in raw_results if r["success"]),
                })

            return AgentResult(
                agent=AgentType.SUPERVISOR,
                result=result_text.strip(),
                confidence=0.9,
                metadata={
                    "raw_results": raw_results,
                    "sub_tasks_count": len(sub_tasks),
                    "success_count": sum(1 for r in raw_results if r["success"]),
                }
            )
        else:
            return AgentResult(
                agent=AgentType.SUPERVISOR,
                result="所有子任务执行失败",
                confidence=0.0,
                success=False,
                error="All sub-tasks failed"
            )

# 全局实例
_supervisor_agent = None


def get_supervisor_agent() -> SupervisorAgent:
    """获取 Supervisor Agent 单例"""
    global _supervisor_agent
    if _supervisor_agent is None:
        _supervisor_agent = SupervisorAgent()
    return _supervisor_agent
