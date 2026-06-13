"""
流式输出处理模块
处理不同模块的流式输出
"""

import json
import time
from typing import AsyncGenerator, Dict, Any
from app.common.user_context import UserContext
from app.multi_agent.router import get_task_router
from app.multi_agent.supervisor import get_supervisor_agent
from monitoring.langfuse_config import create_trace, create_span


class StreamHandler:
    """
    流式输出处理器
    
    功能：
    1. 任务路由（LLM 自动判断）
    2. 调用合适的模块处理
    3. 返回 SSE 格式的流式输出
    """
    
    def __init__(self, user_context: UserContext, session_id: str = None):
        """
        初始化流式处理器
        
        Args:
            user_context: 用户上下文
            session_id: 会话ID（用于获取历史消息）
        """
        self.user_context = user_context
        self.session_id = session_id
        self.router = get_task_router()
        self.supervisor = get_supervisor_agent()
        
        # 获取历史消息
        self.history_data = None
        if session_id:
            from app.rag.session import get_session_manager
            session_mgr = get_session_manager()
            self.history_data = session_mgr.get_history_for_llm(session_id)
    
    def _build_history_context(self) -> str:
        """
        构建历史上下文字符串
        
        Returns:
            格式化的历史上下文文本
        """
        if not self.history_data:
            return ""
        
        parts = []
        
        # 添加纪要
        if self.history_data.get("summary"):
            parts.append(f"【历史纪要】\n{self.history_data['summary']}")
        
        # 添加最近对话
        if self.history_data.get("recent_conversations"):
            recent = []
            for msg in self.history_data["recent_conversations"][-10:]:  # 最近5轮
                role = "用户" if msg["role"] == "user" else "助手"
                content = msg["content"]
                
                # 助手回复：尝试提取可读内容
                if role == "助手":
                    content = self._extract_readable_content(msg)
                
                # 限制长度
                content = content[:300] if content else ""
                if content:
                    recent.append(f"{role}: {content}")
            
            if recent:
                parts.append(f"【最近对话】\n" + "\n".join(recent))
        
        return "\n\n".join(parts)
    
    def _extract_readable_content(self, msg: dict) -> str:
        """
        从消息中提取可读内容
        
        Args:
            msg: 消息字典
        
        Returns:
            可读的文本内容
        """
        content = msg.get("content", "")
        
        # 如果 content 是 JSON 字符串，尝试解析
        if isinstance(content, str) and content.strip().startswith(("{", "[")):
            try:
                import json
                data = json.loads(content)
                
                # 如果是结构化数据，提取摘要或标题
                if isinstance(data, dict):
                    # 优先使用 summary
                    if data.get("summary"):
                        return data["summary"]
                    # 使用 title
                    if data.get("title"):
                        return f"[{data['title']}]"
                    # 提取 data 中的内容
                    if data.get("data"):
                        inner = data["data"]
                        if isinstance(inner, dict):
                            # 卡片类型
                            if inner.get("cards"):
                                cards = inner["cards"]
                                items = [f"{c.get('label', '')}: {c.get('value', '')}" for c in cards[:3]]
                                return ", ".join(items)
                            # 表格类型
                            if inner.get("rows"):
                                return f"[表格数据 {len(inner['rows'])} 行]"
                    # 使用 content 字段
                    if data.get("content"):
                        return data["content"][:200]
            except (json.JSONDecodeError, TypeError):
                pass
        
        # 返回原始内容
        return content
    
    async def process(self, message: str, image_url: str = None) -> AsyncGenerator[str, None]:
        """
        处理聊天请求，返回 SSE 流
        
        Args:
            message: 用户消息
            image_url: 图像 URL（可选）
        
        Yields:
            SSE 格式的数据
        """
        # 保存用户消息到历史
        session_mgr = None
        if self.session_id:
            from app.rag.session import get_session_manager
            session_mgr = get_session_manager()
            session_mgr.add_message(self.session_id, "user", message)

        print(f"[StreamHandler] ========== 收到新请求 ==========")
        print(f"[StreamHandler] 用户消息: {message}")
        print(f"[StreamHandler] 用户ID: {self.user_context.user_id}, 店铺ID: {self.user_context.shop_id}, 角色: {self.user_context.role}")
        print(f"[StreamHandler] 会话ID: {self.session_id}")
        print(f"[StreamHandler] 图片: {'有' if image_url else '无'}")

        # 创建追踪
        trace = create_trace("chat_stream", {
            "message": message[:200],  # 截断过长消息
            "user_id": self.user_context.user_id,
            "shop_id": self.user_context.shop_id,
            "role": self.user_context.role,
        })
        start_time = time.time()
        
        # 收集 AI 回复内容（使用实例属性，以便子方法可以访问）
        self._ai_response_parts = []
        self._ai_response_data_type = None  # 数据类型（text/data）
        self._ai_response_structured_data = None  # 结构化数据
        
        try:
            # 1. 任务路由
            yield self._format_sse("thinking", "正在分析您的问题...", "意图分析")
            
            # 构建店铺上下文
            shop_context = ""
            if self.user_context:
                if self.user_context.shop_name:
                    shop_context += f"店铺名称：{self.user_context.shop_name}\n"
                if self.user_context.role:
                    shop_context += f"用户角色：{self.user_context.role}\n"
            
            # 构建历史上下文（在分析问题时就注入）
            history_context = self._build_history_context()
            if history_context:
                shop_context += f"\n【历史对话】\n{history_context}\n"
            
            print(f"[StreamHandler] 历史上下文长度: {len(history_context)}")
            print(f"[StreamHandler] 店铺上下文长度: {len(shop_context)}")
            
            route_result = await self.router.route(message, has_image=bool(image_url), shop_context=shop_context)

            # 详细记录路由决策
            print(f"[StreamHandler] ========== 路由决策 ==========")
            print(f"[StreamHandler] 模式: {route_result.get('mode')}")
            print(f"[StreamHandler] Agent: {route_result.get('agent')}")
            print(f"[StreamHandler] 推理: {route_result.get('reasoning')}")
            print(f"[StreamHandler] 理解: {route_result.get('understanding')}")
            print(f"[StreamHandler] 复杂度: {route_result.get('complexity')}")

            # 输出问题理解
            understanding = route_result.get("understanding", f"用户想要{message}")
            yield self._format_sse("thinking", understanding, "理解问题")
            
            # 输出分析（如果有）
            analysis = route_result.get("analysis", "")
            if analysis:
                yield self._format_sse("thinking", analysis, "分析问题")
            
            # 输出执行计划
            plan = route_result.get("plan", [])
            if plan:
                plan_items = []
                for step in plan:
                    plan_items.append(f"{step.get('step')}. {step.get('action')}")
                plan_text = "\n".join(plan_items)
                yield self._format_sse("plan", plan_text, "执行计划")
            
            # 记录路由结果
            if trace:
                create_span(trace, "task_route", {
                    "mode": route_result.get("mode"),
                    "agent": route_result.get("agent"),
                    "reasoning": route_result.get("reasoning"),
                    "plan": plan,
                })
            
            # 2. 根据路由结果调用不同模块
            # 获取 Router 的分析结果
            understanding = route_result.get("understanding", f"用户想要{message}")
            analysis = route_result.get("analysis", "")
            plan = route_result.get("plan", [])
            
            # 构建历史上下文
            history_context = self._build_history_context()
            
            # 判断是否需要追问
            if route_result.get("mode") == "clarify":
                # 需要追问或问题无效
                clarification = route_result.get("clarification", "请补充更多信息。")
                self._ai_response_parts.append(clarification)
                self._ai_response_data_type = "text"
                yield self._format_sse("answer", clarification, "提示")
                
                # 发送快捷问题（前端可以显示为快捷按钮）
                quick_questions = route_result.get("quick_questions", [])
                if quick_questions:
                    yield self._format_sse("quick_questions", quick_questions, "快捷问题")
            
            # 判断是否按计划执行
            elif route_result.get("mode") == "single" and plan:
                # 确定实际执行的任务（优先使用 understanding，而不是原始 message）
                actual_task = understanding if understanding and understanding != f"用户想要{message}" else message
                print(f"[StreamHandler] 实际执行任务: {actual_task}")
                
                # 单任务，按计划执行
                async for event in self._execute_plan(actual_task, plan, understanding, analysis, history_context, trace):
                    yield event
            elif route_result.get("mode") == "multi":
                # 多 Agent 任务
                async for event in self._process_multi(message, image_url, trace):
                    yield event
            else:
                # 没有计划，使用传统方式
                route_info = ""
                if understanding:
                    route_info += f"问题理解：{understanding}\n"
                if analysis:
                    route_info += f"分析：{analysis}\n"
                
                async for event in self._process_single(
                    message, route_result.get("agent", "tool"), image_url, trace,
                    route_context=route_result,
                    route_info=route_info,
                    history_context=history_context
                ):
                    yield event
            
            # 3. 完成
            duration_ms = (time.time() - start_time) * 1000
            print(f"[StreamHandler] ========== 请求处理完成 ==========")
            print(f"[StreamHandler] 总耗时: {duration_ms:.0f}ms")

            if trace:
                create_span(trace, "chat_complete", {
                    "duration_ms": duration_ms,
                })
            
            # 保存 AI 回复到历史
            if self.session_id and session_mgr and self._ai_response_parts:
                ai_response = "".join(self._ai_response_parts)
                # 构建完整的消息数据
                message_data = {}
                if self._ai_response_data_type:
                    message_data["data_type"] = self._ai_response_data_type
                if self._ai_response_structured_data:
                    message_data["structured_data"] = self._ai_response_structured_data
                session_mgr.add_message(self.session_id, "assistant", ai_response, **message_data)
            
            yield self._format_sse("done", "", "完成", done=True)
            
        except Exception as e:
            print(f"[StreamHandler] 处理失败: {str(e)}")  # 只在控制台记录
            
            if trace:
                create_span(trace, "chat_error", {"error": str(e)})
            
            # 异常时也要保存友好提示到历史
            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"
            if self.session_id:
                try:
                    from app.rag.session import get_session_manager
                    session_mgr = get_session_manager()
                    session_mgr.add_message(self.session_id, "assistant", friendly_msg)
                except Exception as save_error:
                    print(f"[StreamHandler] 保存错误消息失败: {str(save_error)}")
            
            yield self._format_sse("answer", friendly_msg, "提示")
    
    async def _execute_plan(
        self, 
        message: str, 
        plan: list, 
        understanding: str, 
        analysis: str, 
        history_context: str, 
        trace
    ) -> AsyncGenerator[str, None]:
        """
        按照 Router 的计划逐步执行任务
        
        Args:
            message: 用户原始问题
            plan: 执行计划 [{action, tool, ...}]
            understanding: 问题理解
            analysis: 问题分析
            history_context: 历史上下文
            trace: LangFuse 追踪
        
        Yields:
            SSE 格式的数据
        """
        print(f"[StreamHandler] ========== 开始按计划执行 ==========")
        print(f"[StreamHandler] 用户问题: {message}")
        print(f"[StreamHandler] 问题理解: {understanding}")
        print(f"[StreamHandler] 计划步骤数: {len(plan)}")
        for i, step in enumerate(plan):
            print(f"[StreamHandler]   步骤 {i+1}: {step.get('action', '')} (工具: {step.get('tool', 'llm')})")
        
        step_results = []  # 存储每个步骤的结果（dict 格式）
        
        for i, step in enumerate(plan):
            action = step.get("action", "")
            tool = step.get("tool", "llm")
            
            # 工具名映射（中文 → 英文，兜底方案）
            tool_map = {
                # 中文 → 英文
                "数据查询": "nl2sql",
                "查询数据": "nl2sql",
                "知识检索": "rag",
                "知识问答": "rag",
                "知识查询": "rag",
                "搜索知识": "rag",
                "工具调用": "tool",
                "调用工具": "tool",
                "分析总结": "llm",
                "总结分析": "llm",
                "分析": "llm",
                "总结": "llm",
                # 英文保持不变
                "nl2sql": "nl2sql",
                "rag": "rag",
                "tool": "tool",
                "llm": "llm",
            }
            tool = tool_map.get(tool, tool)
            
            print(f"[StreamHandler] ----- 执行步骤 {i+1}/{len(plan)} -----")
            print(f"[StreamHandler] 动作: {action}")
            print(f"[StreamHandler] 工具: {tool}")
            
            # 输出步骤开始
            yield self._format_sse("processing", f"步骤 {i+1}/{len(plan)}: {action}...", f"步骤 {i+1}")
            
            # 构建步骤上下文（包含之前的步骤结果）
            step_context = f"问题理解：{understanding}\n"
            if analysis:
                step_context += f"分析：{analysis}\n"
            if step_results:
                step_context += "\n之前的执行结果：\n"
                for j, prev in enumerate(step_results):
                    status = "成功" if prev.get("success") else "失败"
                    step_context += f"步骤 {j+1}({prev.get('tool', '')}): {status} - {prev.get('result', prev.get('error', ''))[:200]}\n"
            step_context += f"\n当前任务：{action}"
            
            print(f"[StreamHandler] 步骤上下文长度: {len(step_context)}")
            
            # 根据工具类型执行
            step_result = None
            step_start = time.time()

            if tool == "nl2sql":
                print(f"[StreamHandler] 调用 NL2SQL Agent...")
                step_result = await self._execute_step_nl2sql(step_context, message)
            elif tool == "rag":
                print(f"[StreamHandler] 调用 RAG Agent...")
                step_result = await self._execute_step_rag(step_context, message, history_context)
            elif tool == "llm":
                print(f"[StreamHandler] 调用 LLM Agent...")
                step_result = await self._execute_step_llm(step_context, message, history_context)
            elif tool == "tool":
                print(f"[StreamHandler] 调用 Tool Agent...")
                step_result = await self._execute_step_tool(step_context, message)
            else:
                print(f"[StreamHandler] 未知工具类型: {tool}，使用 LLM")
                step_result = await self._execute_step_llm(step_context, message, history_context)

            step_duration = (time.time() - step_start) * 1000
            print(f"[StreamHandler] 步骤 {i+1} 执行耗时: {step_duration:.0f}ms")
            print(f"[StreamHandler] 步骤 {i+1} 执行结果: {step_result}")
            
            if step_result and step_result.get("success"):
                result_text = step_result.get("result", "")
                
                # 检查结果是否有效（不是"无法"、"抱歉"等拒绝性回答）
                is_valid_result = self._is_valid_result(result_text, action)
                
                if is_valid_result:
                    step_results.append({
                        "action": action, "tool": tool, "success": True,
                        "result": result_text, "error": ""
                    })
                    print(f"[StreamHandler] ✓ 步骤 {i+1} 成功，结果长度: {len(result_text)}")
                    yield self._format_sse("processing", f"✓ 步骤 {i+1} 完成", f"步骤 {i+1}")
                else:
                    # 结果无效，尝试切换工具
                    print(f"[StreamHandler] 步骤 {i+1} 结果无效，尝试切换工具")
                    alt_result = await self._try_alternative_tool(action, message, tool, history_context)
                    
                    if alt_result and alt_result.get("success"):
                        step_results.append({
                            "action": action, "tool": tool, "success": True,
                            "result": alt_result.get("result", ""), "error": ""
                        })
                        print(f"[StreamHandler] ✓ 步骤 {i+1} 切换工具成功")
                        yield self._format_sse("processing", f"✓ 步骤 {i+1} 完成（切换工具）", f"步骤 {i+1}")
                    else:
                        step_results.append({
                            "action": action, "tool": tool, "success": False,
                            "result": "", "error": "结果无效"
                        })
                        print(f"[StreamHandler] ✗ 步骤 {i+1} 切换工具也失败")
                        yield self._format_sse("processing", f"✗ 步骤 {i+1} 失败", f"步骤 {i+1}")
            else:
                error = step_result.get("error", "未知错误") if step_result else "执行失败"
                step_results.append({
                    "action": action, "tool": tool, "success": False,
                    "result": "", "error": error
                })
                print(f"[StreamHandler] ✗ 步骤 {i+1} 失败: {error}")
                yield self._format_sse("processing", f"✗ 步骤 {i+1} 失败: {error}", f"步骤 {i+1}")
        
        # 汇总所有步骤结果
        success_count = len([r for r in step_results if r.get("success")])
        print(f"[StreamHandler] ========== 汇总结果 ==========")
        print(f"[StreamHandler] 成功步骤数: {success_count}/{len(step_results)}")
        yield self._format_sse("processing", "正在汇总结果...", "汇总")

        final_result = await self._final_summarize(
            user_message=message,
            understanding=understanding,
            analysis=analysis,
            plan=plan,
            step_results=step_results,
            history_context=history_context,
        )
        
        print(f"[StreamHandler] 最终结果长度: {len(final_result)}")
        print(f"[StreamHandler] ========== 执行完成 ==========")
        
        # 收集 AI 回复
        self._ai_response_parts.append(final_result)
        self._ai_response_data_type = "text"
        
        yield self._format_sse("answer", final_result, "最终答案")
    
    async def _execute_step_nl2sql(self, context: str, original_task: str) -> dict:
        """执行 NL2SQL 步骤"""
        print(f"[StreamHandler:NL2SQL] ========== 开始执行 ==========")
        print(f"[StreamHandler:NL2SQL] 入参 original_task: {original_task}")
        print(f"[StreamHandler:NL2SQL] 入参 context({len(context)}字符): {context[:300]}...")
        t0 = time.time()
        try:
            from app.multi_agent.nl2sql_agent import NL2SQLAgent

            agent = NL2SQLAgent()
            result = await agent.execute(context, self.user_context)

            duration = (time.time() - t0) * 1000
            print(f"[StreamHandler:NL2SQL] 执行耗时: {duration:.0f}ms")
            print(f"[StreamHandler:NL2SQL] 执行结果: success={result.success}, result_length={len(result.result) if result.result else 0}")
            if result.success:
                print(f"[StreamHandler:NL2SQL] 输出内容: {result.result[:300]}...")
            else:
                print(f"[StreamHandler:NL2SQL] 错误: {result.error}")

            return {
                "success": result.success,
                "result": result.result if result.success else "",
                "error": result.error if not result.success else ""
            }
        except Exception as e:
            duration = (time.time() - t0) * 1000
            print(f"[StreamHandler:NL2SQL] 异常({duration:.0f}ms): {str(e)}")
            return {"success": False, "result": "", "error": str(e)}
    
    async def _execute_step_rag(self, context: str, original_task: str, history_context: str = "") -> dict:
        """执行 RAG 步骤"""
        print(f"[StreamHandler:RAG] ========== 开始执行 ==========")
        print(f"[StreamHandler:RAG] 入参 original_task: {original_task}")
        print(f"[StreamHandler:RAG] 入参 context({len(context)}字符): {context[:300]}...")
        print(f"[StreamHandler:RAG] 入参 history_context({len(history_context)}字符)")
        t0 = time.time()
        try:
            from app.multi_agent.rag_agent import RAGAgent

            agent = RAGAgent()
            result = await agent.execute(
                original_task,
                self.user_context,
                route_context=context,
                history_context=history_context
            )

            duration = (time.time() - t0) * 1000
            print(f"[StreamHandler:RAG] 执行耗时: {duration:.0f}ms")
            print(f"[StreamHandler:RAG] 执行结果: success={result.success}, result_length={len(result.result) if result.result else 0}")
            if result.success:
                print(f"[StreamHandler:RAG] 输出内容: {result.result[:300]}...")

            return {
                "success": result.success,
                "result": result.result if result.success else "",
                "error": result.error if not result.success else ""
            }
        except Exception as e:
            duration = (time.time() - t0) * 1000
            print(f"[StreamHandler:RAG] 异常({duration:.0f}ms): {str(e)}")
            return {"success": False, "result": "", "error": str(e)}
    
    async def _execute_step_llm(self, context: str, original_task: str, history_context: str) -> dict:
        """执行 LLM 步骤"""
        print(f"[StreamHandler:LLM] ========== 开始执行 ==========")
        print(f"[StreamHandler:LLM] 入参 original_task: {original_task}")
        print(f"[StreamHandler:LLM] 入参 context({len(context)}字符): {context[:300]}...")
        t0 = time.time()
        try:
            from app.multi_agent.llm_agent import LLMAgent

            agent = LLMAgent()
            result = await agent.execute(context, self.user_context, history_context=history_context)

            duration = (time.time() - t0) * 1000
            print(f"[StreamHandler:LLM] 执行耗时: {duration:.0f}ms")
            print(f"[StreamHandler:LLM] 执行结果: success={result.success}, result_length={len(result.result) if result.result else 0}")
            if result.success:
                print(f"[StreamHandler:LLM] 输出内容: {result.result[:300]}...")

            return {
                "success": result.success,
                "result": result.result if result.success else "",
                "error": result.error if not result.success else ""
            }
        except Exception as e:
            duration = (time.time() - t0) * 1000
            print(f"[StreamHandler:LLM] 异常({duration:.0f}ms): {str(e)}")
            return {"success": False, "result": "", "error": str(e)}
    
    async def _execute_step_tool(self, context: str, original_task: str) -> dict:
        """执行 Tool 步骤"""
        print(f"[StreamHandler:Tool] ========== 开始执行 ==========")
        print(f"[StreamHandler:Tool] 入参 original_task: {original_task}")
        print(f"[StreamHandler:Tool] 入参 context({len(context)}字符): {context[:300]}...")
        t0 = time.time()
        try:
            from app.tools.agent_loop import run_agent

            result = await run_agent(
                question=context,
                user_context=self.user_context,
                max_iterations=3,
            )

            duration = (time.time() - t0) * 1000
            print(f"[StreamHandler:Tool] 执行耗时: {duration:.0f}ms")
            print(f"[StreamHandler:Tool] 执行结果: success={result.get('success', False)}")
            if result.get("success"):
                print(f"[StreamHandler:Tool] 输出内容: {str(result.get('answer', ''))[:300]}...")
            
            return {
                "success": result.get("success", False),
                "result": result.get("answer", ""),
                "error": result.get("error", "")
            }
        except Exception as e:
            duration = (time.time() - t0) * 1000
            print(f"[StreamHandler:Tool] 异常({duration:.0f}ms): {str(e)}")
            return {"success": False, "result": "", "error": str(e)}
    
    def _is_valid_result(self, result: str, action: str) -> bool:
        """
        检查结果是否有效（不是拒绝性回答）
        
        Args:
            result: 执行结果
            action: 原始任务
        
        Returns:
            是否有效
        """
        if not result or len(result.strip()) < 10:
            return False
        
        # 检查是否是拒绝性回答
        rejection_keywords = [
            "无法", "不能", "抱歉", "超出", "不是我能", "不支持",
            "无法提供", "无法获取", "无法查询", "无法回答",
            "sorry", "cannot", "can't",
        ]
        
        result_lower = result.lower()
        for keyword in rejection_keywords:
            if keyword in result_lower:
                print(f"[StreamHandler] 结果包含拒绝性关键词: {keyword}")
                return False
        
        return True
    
    async def _try_alternative_tool(self, action: str, original_task: str, failed_tool: str, history_context: str) -> dict:
        """
        智能切换工具（根据任务内容和失败原因选择替代工具）
        
        Args:
            action: 任务描述
            original_task: 原始用户问题
            failed_tool: 失败的工具
            history_context: 历史上下文
        
        Returns:
            执行结果
        """
        print(f"[StreamHandler] 智能切换工具，原工具: {failed_tool}")
        
        # 分析任务内容，判断应该使用哪个工具
        task_lower = (action + " " + original_task).lower()
        
        # 判断任务类型
        is_data_query = any(kw in task_lower for kw in ["查询", "数据", "金额", "数量", "支出", "收入", "多少"])
        is_knowledge = any(kw in task_lower for kw in ["什么是", "如何", "怎么", "定义", "解释"])
        is_realtime = any(kw in task_lower for kw in ["天气", "新闻", "实时", "今天", "最新"])
        
        # 根据任务类型和失败工具，智能选择替代工具
        alt_tool = None
        
        if failed_tool == "llm":
            # LLM 失败（无法回答）
            if is_data_query:
                alt_tool = "nl2sql"  # 数据问题用 NL2SQL
            elif is_realtime:
                alt_tool = "rag"  # 实时信息用 RAG（会搜索互联网）
            else:
                alt_tool = "rag"  # 默认用 RAG
        
        elif failed_tool == "rag":
            # RAG 失败（知识库无结果）
            if is_data_query:
                alt_tool = "nl2sql"  # 数据问题用 NL2SQL
            elif is_realtime:
                # 实时信息应该已经搜索过互联网了，用 LLM 尝试
                alt_tool = "llm"
            else:
                alt_tool = "llm"
        
        elif failed_tool == "nl2sql":
            # NL2SQL 失败（SQL 错误）
            if is_knowledge:
                alt_tool = "rag"  # 知识问题用 RAG
            else:
                alt_tool = "llm"  # 分析问题用 LLM
        
        else:
            # 其他情况，默认用 RAG
            alt_tool = "rag"
        
        print(f"[StreamHandler] 选择替代工具: {alt_tool}")
        
        if alt_tool:
            result = None
            if alt_tool == "rag":
                result = await self._execute_step_rag(action, original_task)
            elif alt_tool == "llm":
                result = await self._execute_step_llm(action, original_task, history_context)
            elif alt_tool == "nl2sql":
                result = await self._execute_step_nl2sql(action, original_task)
            
            if result and result.get("success"):
                result_text = result.get("result", "")
                if self._is_valid_result(result_text, action):
                    print(f"[StreamHandler] 替代工具 {alt_tool} 成功")
                    return result
        
        print(f"[StreamHandler] 替代工具也失败")
        return {"success": False, "result": "", "error": "替代工具也失败"}
    
    async def _final_summarize(
        self,
        user_message: str,
        understanding: str,
        analysis: str,
        plan: list,
        step_results: list,
        history_context: str,
    ) -> str:
        """
        最终汇总步骤（独立于工具执行）

        把所有上下文信息 + system_prompts 一起提交给 LLM 综合分析输出。
        system_prompts 中的角色定义、安全规则、合规规则具有最高优先级。

        Args:
            user_message: 用户原始消息
            understanding: Router 对问题的理解
            analysis: Router 的分析
            plan: 执行计划
            step_results: 每步结果 [{action, tool, success, result, error}]
            history_context: 历史上下文

        Returns:
            LLM 汇总生成的最终回答
        """
        try:
            from app.llm import get_chat_llm
            from app.common.system_prompts import build_summarize_prompt
            from langchain_core.messages import SystemMessage, HumanMessage

            llm = get_chat_llm()

            # 构建完整 Prompt（包含 system_prompts 最高优先级）
            prompt = build_summarize_prompt(
                user_message=user_message,
                understanding=understanding,
                analysis=analysis,
                plan=plan,
                step_results=step_results,
                history_context=history_context,
                display_name=self.user_context.display_name or "用户",
                username=self.user_context.username or "",
                role=self.user_context.role or "店员",
                shop_name=self.user_context.shop_name or "店铺",
                shop_id=self.user_context.shop_id,
            )

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            print(f"[StreamHandler] 汇总失败: {str(e)}")
            # 降级：直接返回成功步骤的结果
            success_results = [r.get("result", "") for r in step_results if r.get("success") and r.get("result")]
            return "\n\n".join(success_results) if success_results else "抱歉，处理过程中出现问题，请稍后重试。"
    
    async def _process_single(
        self, 
        message: str, 
        agent_type: str, 
        image_url: str, 
        trace,
        route_context: dict = None,
        route_info: str = "",
        history_context: str = ""
    ) -> AsyncGenerator[str, None]:
        """
        处理单 Agent 任务
        
        Args:
            message: 用户消息
            agent_type: Agent 类型
            image_url: 图像 URL
            trace: LangFuse 追踪
            route_context: 路由分析结果（包含 understanding、plan 等）
            route_info: 格式化的路由上下文
            history_context: 历史上下文
        
        Yields:
            SSE 格式的数据
        """
        if agent_type == "rag":
            async for event in self._process_rag(message, trace, route_context=route_context, route_info=route_info, history_context=history_context):
                yield event
        
        elif agent_type == "nl2sql":
            async for event in self._process_nl2sql(message, trace, route_context=route_context, route_info=route_info, history_context=history_context):
                yield event
        
        elif agent_type == "tool":
            async for event in self._process_tool(message, trace, route_context=route_context, route_info=route_info, history_context=history_context):
                yield event
        
        elif agent_type == "llm":
            async for event in self._process_llm(message, trace, route_info=route_info, history_context=history_context):
                yield event
        
        elif agent_type == "vision":
            async for event in self._process_vision(message, image_url, trace):
                yield event
        
        elif agent_type == "llm":
            async for event in self._process_llm(message, trace, route_info=route_info, history_context=history_context):
                yield event
        
        else:
            yield self._format_sse("error", f"未知的 Agent 类型: {agent_type}", "错误")
    
    async def _process_llm(self, message: str, trace, route_info: str = "", history_context: str = "") -> AsyncGenerator[str, None]:
        """
        处理 LLM 任务（上下文分析、总结建议等）
        
        Args:
            message: 用户消息
            trace: LangFuse 追踪
            route_info: 格式化的路由上下文
            history_context: 历史上下文
        
        Yields:
            SSE 格式的数据
        """
        yield self._format_sse("processing", "正在分析...", "分析")
        
        try:
            from app.multi_agent.llm_agent import LLMAgent
            
            agent = LLMAgent()
            result = await agent.execute(message, self.user_context, route_info=route_info, history_context=history_context)
            
            if result.success:
                self._ai_response_parts.append(result.result)
                self._ai_response_data_type = "text"
                yield self._format_sse("answer", result.result, "回答")
            else:
                friendly_msg = "抱歉，无法回答您的问题，请稍后重试。"
                self._ai_response_parts.append(friendly_msg)
                self._ai_response_data_type = "text"
                yield self._format_sse("answer", friendly_msg, "提示")
        except Exception as e:
            print(f"[StreamHandler] LLM 处理失败: {str(e)}")
            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"
            self._ai_response_parts.append(friendly_msg)
            self._ai_response_data_type = "text"
            yield self._format_sse("answer", friendly_msg, "提示")
    
    async def _process_multi(
        self, 
        message: str, 
        image_url: str, 
        trace
    ) -> AsyncGenerator[str, None]:
        """
        处理多 Agent 任务
        
        Args:
            message: 用户消息
            image_url: 图像 URL
            trace: LangFuse 追踪
        
        Yields:
            SSE 格式的数据
        """
        import asyncio
        
        yield self._format_sse("processing", "正在分析问题并拆分任务...", "任务分析")
        
        # 创建进度队列
        progress_queue = asyncio.Queue()
        
        # 定义进度回调函数
        async def progress_callback(step, content, status="processing"):
            await progress_queue.put((step, content, status))
        
        # 设置回调
        self.supervisor.set_progress_callback(progress_callback)
        
        # 构建历史上下文
        history_context = self._build_history_context()
        
        # 启动 Supervisor 执行任务
        async def run_supervisor():
            try:
                result = await self.supervisor.execute(
                    task=message,
                    context=self.user_context,
                    image_url=image_url,
                    history_context=history_context,
                )
                await progress_queue.put(("__done__", result, "done"))
            except Exception as e:
                await progress_queue.put(("__error__", str(e), "error"))
        
        # 并发执行 Supervisor 和进度输出
        supervisor_task = asyncio.create_task(run_supervisor())
        
        # 记录执行结果
        final_result = None
        
        while True:
            try:
                # 等待进度信息（超时 0.5 秒）
                step, content, status = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                
                if step == "__done__":
                    final_result = content
                    break
                elif step == "__error__":
                    yield self._format_sse("answer", "抱歉，处理过程中出现问题，请稍后重试。", "提示")
                    return
                else:
                    # 输出进度
                    yield self._format_sse(status, content, step)
            except asyncio.TimeoutError:
                # 超时，检查任务是否完成
                if supervisor_task.done():
                    # 任务已完成，清空队列中剩余的消息
                    while not progress_queue.empty():
                        try:
                            step, content, status = progress_queue.get_nowait()
                            if step == "__done__":
                                final_result = content
                                break
                            elif step != "__error__":
                                yield self._format_sse(status, content, step)
                        except asyncio.QueueEmpty:
                            break
                    break
                continue
        
        # 等待任务完成
        await supervisor_task
        
        # 记录执行结果
        if trace and final_result:
            create_span(trace, "multi_agent_result", {
                "success": final_result.success,
                "confidence": final_result.confidence,
                "result_length": len(final_result.result) if final_result.result else 0,
            })
        
        # 输出最终结果
        if final_result and final_result.success:
            # 收集 AI 回复
            self._ai_response_parts.append(final_result.result)
            self._ai_response_data_type = "text"
            yield self._format_sse("answer", final_result.result, "最终答案")
        else:
            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"
            self._ai_response_parts.append(friendly_msg)
            self._ai_response_data_type = "text"
            yield self._format_sse("answer", friendly_msg, "提示")
    
    async def _process_rag(self, message: str, trace, route_context: dict = None, route_info: str = "", history_context: str = "") -> AsyncGenerator[str, None]:
        """
        处理 RAG 任务（调用 RAGAgent，支持互联网搜索和历史上下文）
        
        Args:
            message: 用户消息
            trace: LangFuse 追踪
            route_context: 路由分析结果
            route_info: 格式化的路由上下文
            history_context: 历史上下文
        
        Yields:
            SSE 格式的数据
        """
        yield self._format_sse("processing", "正在检索知识库...", "知识检索")
        
        try:
            from app.multi_agent.rag_agent import RAGAgent
            
            agent = RAGAgent()
            result = await agent.execute(
                message, 
                self.user_context, 
                history_context=history_context,
                route_context=route_info
            )
            
            if result.success:
                answer = result.result
                
                # 如果答案为空，使用默认提示
                if not answer or len(answer.strip()) < 5:
                    answer = "抱歉，暂时无法回答您的问题，请稍后重试。"
                
                # 收集 AI 回复
                self._ai_response_parts.append(answer)
                self._ai_response_data_type = "text"
                
                # 流式输出答案
                chunk_size = 20
                for i in range(0, len(answer), chunk_size):
                    chunk = answer[i:i + chunk_size]
                    yield self._format_sse("answer", chunk, "回答生成", done=False)
                
                # 记录结果
                if trace:
                    create_span(trace, "rag_result", {
                        "answer_length": len(answer),
                        "confidence": result.confidence,
                        "web_searched": result.metadata.get("web_searched", False),
                    })
                
                yield self._format_sse("answer", "", "回答完成", done=True)
            else:
                # 失败时友好提示
                friendly_msg = "抱歉，知识检索失败，请稍后重试。"
                self._ai_response_parts.append(friendly_msg)
                self._ai_response_data_type = "text"
                
                yield self._format_sse("answer", friendly_msg, "提示")
            
        except Exception as e:
            print(f"[StreamHandler] RAG 处理失败: {str(e)}")
            
            friendly_msg = "抱歉，知识检索出现问题，请稍后重试。"
            self._ai_response_parts.append(friendly_msg)
            self._ai_response_data_type = "text"
            
            yield self._format_sse("answer", friendly_msg, "提示")
    
    async def _process_nl2sql(self, message: str, trace, route_context: dict = None, route_info: str = "", history_context: str = "") -> AsyncGenerator[str, None]:
        """
        处理 NL2SQL 任务（调用 NL2SQLAgent，带自动修复和历史上下文）
        
        Args:
            message: 用户消息
            trace: LangFuse 追踪
            route_context: 路由分析结果（包含 understanding、plan 等）
            route_info: 格式化的路由上下文
            history_context: 历史上下文
        
        Yields:
            SSE 格式的数据
        """
        yield self._format_sse("processing", "正在查询数据...", "数据查询")
        
        try:
            from app.multi_agent.nl2sql_agent import NL2SQLAgent
            
            agent = NL2SQLAgent()
            result = await agent.execute(
                message, 
                self.user_context, 
                history_context=history_context,
                route_context=route_info
            )
            
            if result.success:
                # 成功：格式化为结构化数据
                from app.formatter.data_formatter import get_data_formatter
                formatter = get_data_formatter()
                structured_data = await formatter.format_with_llm(message, result.result)
                
                # 收集 AI 回复
                if isinstance(structured_data, dict) and "data" in structured_data:
                    self._ai_response_parts.append(json.dumps(structured_data["data"], ensure_ascii=False))
                else:
                    self._ai_response_parts.append(result.result[:500])
                self._ai_response_data_type = "data"
                self._ai_response_structured_data = structured_data
                
                # 记录结果
                if trace:
                    create_span(trace, "nl2sql_result", {
                        "success": True,
                        "attempts": result.metadata.get("attempts", 1) if result.metadata else 1,
                        "display_type": structured_data.get("display_type"),
                    })
                
                yield self._format_sse("data", structured_data, "查询结果")
            else:
                # 失败：友好提示，不暴露错误细节
                print(f"[StreamHandler] NL2SQL 失败: {result.error}")  # 只在控制台记录
                
                friendly_msg = "抱歉，数据查询失败，请稍后重试或换个方式提问。"
                self._ai_response_parts.append(friendly_msg)
                self._ai_response_data_type = "text"
                
                yield self._format_sse("answer", friendly_msg, "提示")
        
        except Exception as e:
            # 异常：友好提示，不暴露错误细节
            print(f"[StreamHandler] NL2SQL 异常: {str(e)}")  # 只在控制台记录
            
            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"
            self._ai_response_parts.append(friendly_msg)
            self._ai_response_data_type = "text"
            
            yield self._format_sse("answer", friendly_msg, "提示")
    
    async def _process_llm(self, message: str, trace, route_info: str = "", history_context: str = "") -> AsyncGenerator[str, None]:
        """
        处理 LLM 任务（上下文分析、总结建议等）
        
        Args:
            message: 用户消息
            trace: LangFuse 追踪
            route_info: 格式化的路由上下文
            history_context: 历史上下文
        
        Yields:
            SSE 格式的数据
        """
        yield self._format_sse("processing", "正在分析...", "分析")
        
        try:
            from app.multi_agent.llm_agent import LLMAgent
            
            agent = LLMAgent()
            result = await agent.execute(message, self.user_context, route_info=route_info, history_context=history_context)
            
            if result.success:
                self._ai_response_parts.append(result.result)
                self._ai_response_data_type = "text"
                yield self._format_sse("answer", result.result, "回答")
            else:
                friendly_msg = "抱歉，无法回答您的问题，请稍后重试。"
                self._ai_response_parts.append(friendly_msg)
                self._ai_response_data_type = "text"
                yield self._format_sse("answer", friendly_msg, "提示")
        except Exception as e:
            print(f"[StreamHandler] LLM 处理失败: {str(e)}")
            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"
            self._ai_response_parts.append(friendly_msg)
            self._ai_response_data_type = "text"
            yield self._format_sse("answer", friendly_msg, "提示")
    
    async def _process_tool(self, message: str, trace, route_context: dict = None, route_info: str = "", history_context: str = "") -> AsyncGenerator[str, None]:
        """
        处理 Tool 任务
        
        Args:
            message: 用户消息
            trace: LangFuse 追踪
            route_context: 路由分析结果
            route_info: 格式化的路由上下文
            history_context: 历史上下文
        
        Yields:
            SSE 格式的数据
        """
        yield self._format_sse("processing", "正在调用工具...", "工具调用")
        
        try:
            from app.tools.agent_loop import run_agent
            
            # 合并上下文
            combined_context = route_info
            if history_context:
                combined_context = f"{route_info}\n\n{history_context}" if route_info else history_context
            
            result = await run_agent(
                question=message,
                user_context=self.user_context,
                max_iterations=3,
                history_context=combined_context,
            )
            
            # 记录结果
            if trace:
                create_span(trace, "tool_result", {
                    "iterations": result.get("iterations", 0),
                    "tool_calls_count": result.get("tool_calls_count", 0),
                    "answer_length": len(result.get("answer", "")),
                })
            
            # 检查是否需要确认框
            answer = result.get("answer", "")
            if isinstance(answer, dict) and answer.get("type") == "confirm":
                # 返回确认框数据
                yield self._format_sse("confirm", answer, "确认操作")
            else:
                # 收集 AI 回复（使用 json.dumps 确保是 JSON 格式）
                if isinstance(answer, dict):
                    self._ai_response_parts.append(json.dumps(answer, ensure_ascii=False))
                else:
                    self._ai_response_parts.append(str(answer))
                self._ai_response_data_type = "data"
                
                # 使用 LLM 格式化为结构化数据
                from app.formatter.data_formatter import get_data_formatter
                formatter = get_data_formatter()
                structured_data = await formatter.format_with_llm(message, str(answer))
                
                # 保存结构化数据
                self._ai_response_structured_data = structured_data
                
                # 记录结果
                if trace:
                    create_span(trace, "tool_result_formatted", {
                        "display_type": structured_data.get("display_type"),
                    })
                
                yield self._format_sse("data", structured_data, "工具结果")
            
        except Exception as e:
            print(f"[StreamHandler] Tool 处理失败: {str(e)}")  # 只在控制台记录
            
            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"
            self._ai_response_parts.append(friendly_msg)
            self._ai_response_data_type = "text"
            
            yield self._format_sse("answer", friendly_msg, "提示")
    
    async def _process_confirm(
        self, 
        action: str, 
        params: dict, 
        trace
    ) -> AsyncGenerator[str, None]:
        """
        处理确认框执行
        
        Args:
            action: 操作类型
            params: 操作参数
            trace: LangFuse 追踪
        
        Yields:
            SSE 格式的数据
        """
        yield self._format_sse("processing", f"正在执行 {action}...", "执行操作")
        
        try:
            from app.tools import EXECUTE_FUNCTIONS
            
            # 获取执行函数
            execute_func = EXECUTE_FUNCTIONS.get(action)
            if not execute_func:
                yield self._format_sse("error", f"未知的操作类型: {action}", "错误")
                return
            
            # 添加操作人ID
            if self.user_context:
                params["operator_id"] = self.user_context.user_id
            
            # 执行操作
            result = execute_func(**params)
            
            # 记录结果
            if trace:
                create_span(trace, "confirm_result", {
                    "action": action,
                    "result": result,
                })
            
            yield self._format_sse("answer", result, "操作结果")
            
        except Exception as e:
            print(f"[StreamHandler] 确认执行失败: {str(e)}")  # 只在控制台记录
            
            friendly_msg = "抱歉，操作执行失败，请稍后重试。"
            self._ai_response_parts.append(friendly_msg)
            self._ai_response_data_type = "text"
            
            yield self._format_sse("answer", friendly_msg, "提示")
    
    async def _process_vision(
        self, 
        message: str, 
        image_url: str, 
        trace
    ) -> AsyncGenerator[str, None]:
        """
        处理 Vision 任务
        
        Args:
            message: 用户消息
            image_url: 图像 URL
            trace: LangFuse 追踪
        
        Yields:
            SSE 格式的数据
        """
        yield self._format_sse("processing", "正在识别图像...", "图像识别")
        
        try:
            from app.multi_agent.vision_agent import get_vision_agent
            
            agent = get_vision_agent()
            result = await agent.execute(
                task=message,
                context=self.user_context,
                image_url=image_url,
            )
            
            # 记录结果
            if trace:
                create_span(trace, "vision_result", {
                    "success": result.success,
                    "confidence": result.confidence,
                    "result_length": len(result.result) if result.result else 0,
                })
            
            if result.success:
                self._ai_response_parts.append(result.result)
                self._ai_response_data_type = "text"
                yield self._format_sse("answer", result.result, "识别结果")
            else:
                print(f"[StreamHandler] Vision 失败: {result.error}")  # 只在控制台记录
                
                friendly_msg = "抱歉，图像识别失败，请稍后重试。"
                self._ai_response_parts.append(friendly_msg)
                self._ai_response_data_type = "text"
                
                yield self._format_sse("answer", friendly_msg, "提示")
            
        except Exception as e:
            print(f"[StreamHandler] Vision 异常: {str(e)}")  # 只在控制台记录
            
            friendly_msg = "抱歉，图像识别出现问题，请稍后重试。"
            self._ai_response_parts.append(friendly_msg)
            self._ai_response_data_type = "text"
            
            yield self._format_sse("answer", friendly_msg, "提示")
    
    def _format_sse(self, type: str, content: str, step: str, done: bool = False) -> str:
        """
        格式化 SSE 数据（同时记录日志）

        Args:
            type: 数据类型（thinking/processing/tool_result/answer/done/error）
            content: 内容
            step: 步骤名称
            done: 是否完成

        Returns:
            SSE 格式的数据
        """
        # 截断过长内容用于日志显示
        content_preview = str(content)[:200] + "..." if len(str(content)) > 200 else str(content)
        print(f"[SSE] ➤ type={type}, step={step}, done={done}, content={content_preview}")

        data = {
            "type": type,
            "content": content,
            "step": step,
            "done": done,
        }
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
