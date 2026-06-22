"""
流式输出处理模块
处理不同模块的流式输出
"""

import json
import asyncio
import time
from typing import AsyncGenerator, Dict, Any
from app.common.user_context import UserContext
from app.tools import TOOL_DISPLAY_NAMES
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

                yield self._format_sse("error", clarification, "错误")

                # 发送快捷问题（在 done 之前，确保前端能收到）
                quick_questions = route_result.get("quick_questions", [])
                if quick_questions:
                    yield self._format_sse("quick_questions", quick_questions, "快捷问题")

                yield self._format_sse("done", "", "完成", done=True)

            

            # 判断是否按计划执行

            elif route_result.get("mode") == "single" and plan:

                # 确定实际执行的任务（优先使用 understanding，而不是原始 message）

                actual_task = understanding if understanding and understanding != f"用户想要{message}" else message

                print(f"[StreamHandler] 实际执行任务: {actual_task}")

                

                # 单任务，按计划执行

                async for event in self._execute_plan(actual_task, plan, understanding, analysis, history_context, trace, original_message=message, route_context=route_result):

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

            

            yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

    

    async def _execute_plan(

        self,

        message: str,

        plan: list,

        understanding: str,

        analysis: str,

        history_context: str,

        trace,

        original_message: str = "",

        route_context: dict = None,

    ) -> AsyncGenerator[str, None]:

        """

        按照 Router 的计划逐步执行任务



        Args:

            message: Router 理解后的任务描述

            plan: 执行计划 [{action, tool, ...}]

            understanding: 问题理解

            analysis: 问题分析

            history_context: 历史上下文

            trace: LangFuse 追踪

            original_message: 用户原始消息（用于 RAG 追问判断）

            route_context: 路由上下文（Router 返回的完整结果，包含 tool_name 等）

        

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

            # tool 为空时直接用 LLM 回答（不支持的操作等场景）
            if not tool or tool.strip() == "":
                print(f"[StreamHandler] 工具为空，直接用 LLM 回答")
                step_result = await self._execute_step_llm(step_context, message, history_context)

            elif tool == "nl2sql":
                print(f"[StreamHandler] 调用 NL2SQL Agent...")
                step_result = await self._execute_step_nl2sql(step_context, message)

            elif tool == "rag":
                print(f"[StreamHandler] 调用 RAG Agent...")
                step_result = await self._execute_step_rag(step_context, message, history_context, original_question=original_message or message)

            elif tool == "llm":
                print(f"[StreamHandler] 调用 LLM Agent...")
                step_result = await self._execute_step_llm(step_context, message, history_context)

            elif tool == "tool":
                print(f"[StreamHandler] 调用 Tool Agent...")
                step_result = await self._execute_step_tool(step_context, message)

            else:

                # 检查是否是 TOOL_MAP 中的具体工具名（如 query_refunds, refund_approve 等）

                from app.tools import TOOL_MAP

                if tool in TOOL_MAP:
                    print(f"[StreamHandler] 直接调用工具: {tool}")
                    step_result = await self._execute_tool_direct(tool, message, route_context)
                    # 参数不完整时 fallback 到 AgentLoop
                    if step_result and step_result.get("fallback"):
                        print(f"[StreamHandler] {tool} 参数不完整，fallback 到 AgentLoop")
                        step_result = await self._execute_step_tool(step_context, message)
                    # 确认框类型：保存确认框消息到 session，再发 SSE confirm 事件
                    elif step_result and step_result.get("confirm_data"):
                        confirm_data = step_result["confirm_data"]
                        # 保存确认框消息到 session（持久化）
                        if self.session_id:
                            try:
                                from app.rag.session import get_session_manager
                                session_mgr = get_session_manager()
                                confirm_text = f"【确认操作】{confirm_data.get('title', '')}\n{confirm_data.get('message', '')}"
                                session_mgr.add_message(self.session_id, "assistant", confirm_text)
                            except Exception as e:
                                print(f"[StreamHandler] 保存确认框消息失败: {str(e)}")
                        yield self._format_sse("confirm", confirm_data, "确认操作")
                        return
                    # 批量确认类型：多个操作需要用户确认
                    elif step_result and step_result.get("batch_confirm"):
                        batch_data = step_result["batch_confirm"]
                        # 保存到 session
                        if self.session_id:
                            try:
                                from app.rag.session import get_session_manager
                                session_mgr = get_session_manager()
                                ops = batch_data.get("operations", [])
                                ops_desc_parts = []
                                for op in ops:
                                    tool_name = op.get("tool_name", op.get("action", ""))
                                    display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
                                    title = op.get("title", display_name)
                                    details = op.get("details", {})
                                    detail_str = "、".join([f"{k}:{v}" for k, v in details.items()]) if details else ""
                                    ops_desc_parts.append(f"{title}（{detail_str}）" if detail_str else title)
                                ops_desc = "；".join(ops_desc_parts)
                                session_mgr.add_message(self.session_id, "assistant", f"【待确认操作】{ops_desc}")
                            except Exception as e:
                                print(f"[StreamHandler] 保存批量确认消息失败: {str(e)}")
                        yield self._format_sse("batch_confirm", batch_data, "批量确认")
                        return
                    # 多选列表类型：保存选择列表消息到 session，再发 SSE select 事件
                    elif step_result and step_result.get("select_data"):
                        select_data = step_result["select_data"]
                        # 保存选择列表消息到 session（持久化，含完整信息）
                        if self.session_id:
                            try:
                                from app.rag.session import get_session_manager
                                session_mgr = get_session_manager()
                                tool_name = select_data.get("tool_name", "")
                                display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
                                items = select_data.get("items", [])
                                # 构建完整的存储文本
                                lines = [f"【{display_name}】找到 {len(items)} 条记录："]
                                for idx, item in enumerate(items, 1):
                                    name = item.get("nickname") or item.get("customer_name") or "未知"
                                    pkg = item.get("package_name") or ""
                                    amount = item.get("refund_amount") or item.get("amount") or ""
                                    reason = item.get("reason") or ""
                                    parts = [name]
                                    if pkg:
                                        parts.append(pkg)
                                    if amount:
                                        parts.append(f"¥{amount}")
                                    if reason:
                                        parts.append(reason)
                                    lines.append(f"{idx}. {' - '.join(parts)}")
                                fields = select_data.get("fields", [])
                                if fields:
                                    field_names = [f.get("label", f.get("name", "")) for f in fields]
                                    lines.append(f"\n请填写：{', '.join(field_names)}")
                                select_text = "\n".join(lines)
                                session_mgr.add_message(self.session_id, "assistant", select_text)
                            except Exception as e:
                                print(f"[StreamHandler] 保存选择列表消息失败: {str(e)}")
                        yield self._format_sse("select", select_data, "多选操作")
                        return
                else:

                    # 未知 tool 类型：打回 Router 重新生成

                    print(f"[StreamHandler] 未知工具类型: {tool}，打回重新生成")

                    valid_tools = ", ".join(sorted(TOOL_MAP.keys()))

                    retry_context = (

                        f"{step_context}\n\n"

                        f"【重要纠错】你上一次选择了无效的工具 '{tool}'，这个工具不存在。"

                        f"你必须从以下有效工具中选择一个：{valid_tools}。"

                        f"禁止使用其他名称，禁止使用描述性名称。"

                    )

                    step_result = await self._execute_step_tool(retry_context, message)



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

        # 流式调用 LLM 汇总，同时收集流式输出内容
        streaming_chunks = []
        async for sse_event in self._final_summarize_stream(
            user_message=message,
            understanding=understanding,
            analysis=analysis,
            plan=plan,
            step_results=step_results,
            history_context=history_context,
        ):
            yield sse_event
            # 收集流式输出的 answer 事件内容
            # sse_event 是 SSE 格式字符串: "data: {json}\n\n"
            if isinstance(sse_event, str) and sse_event.startswith("data: "):
                try:
                    event_data = json.loads(sse_event[6:].strip())
                    if event_data.get("type") == "answer":
                        chunk_content = event_data.get("content", "")
                        if chunk_content:
                            streaming_chunks.append(chunk_content)
                except (json.JSONDecodeError, IndexError):
                    pass

        print(f"[StreamHandler] ========== 执行完成 ==========")

        # 保存到 session：优先使用 LLM 格式化后的内容，降级使用原始步骤结果
        if streaming_chunks:
            self._ai_response_parts.append("".join(streaming_chunks))
        else:
            success_results = [r.get("result", "") for r in step_results if r.get("success") and r.get("result")]
            final_result = "\n\n".join(success_results) if success_results else ""
            self._ai_response_parts.append(final_result)
        self._ai_response_data_type = "text"

    # NL2SQL 结果缓存（避免重复查询）
    _nl2sql_cache = {}  # key: f"{shop_id}:{context_hash}", value: {"result": ..., "timestamp": ...}
    _nl2sql_cache_ttl = 300  # 缓存过期时间（秒）

    async def _execute_step_nl2sql(self, context: str, original_task: str) -> dict:

        """执行 NL2SQL 步骤（带缓存）"""

        print(f"[StreamHandler:NL2SQL] ========== 开始执行 ==========")

        print(f"[StreamHandler:NL2SQL] 入参 original_task: {original_task}")

        print(f"[StreamHandler:NL2SQL] 入参 context({len(context)}字符): {context}")

        # 检查缓存（用 original_task 做 key，而不是 context，因为 context 包含动态内容）
        import hashlib
        cache_key = f"{self.user_context.shop_id}:{hashlib.md5(original_task.encode()).hexdigest()}"
        now = time.time()
        
        if cache_key in self._nl2sql_cache:
            cached = self._nl2sql_cache[cache_key]
            if now - cached["timestamp"] < self._nl2sql_cache_ttl:
                print(f"[StreamHandler:NL2SQL] 命中缓存，跳过执行")
                return cached["result"]
            else:
                # 缓存过期，删除
                del self._nl2sql_cache[cache_key]

        t0 = time.time()

        try:

            from app.multi_agent.nl2sql_agent import NL2SQLAgent



            agent = NL2SQLAgent()

            result = await agent.execute(context, self.user_context)



            duration = (time.time() - t0) * 1000

            print(f"[StreamHandler:NL2SQL] 执行耗时: {duration:.0f}ms")

            print(f"[StreamHandler:NL2SQL] 执行结果: success={result.success}, result_length={len(result.result) if result.result else 0}")

            if result.success:

                print(f"[StreamHandler:NL2SQL] 输出内容: {result.result}")

            else:

                print(f"[StreamHandler:NL2SQL] 错误: {result.error}")



            result_dict = {

                "success": result.success,

                "result": result.result if result.success else "",

                "error": result.error if not result.success else ""

            }

            # 缓存成功结果
            if result.success:
                self._nl2sql_cache[cache_key] = {
                    "result": result_dict,
                    "timestamp": now
                }
                # 清理过期缓存
                if len(self._nl2sql_cache) > 100:
                    expired_keys = [k for k, v in self._nl2sql_cache.items() if now - v["timestamp"] > self._nl2sql_cache_ttl]
                    for k in expired_keys:
                        del self._nl2sql_cache[k]

            return result_dict

        except Exception as e:

            duration = (time.time() - t0) * 1000

            print(f"[StreamHandler:NL2SQL] 异常({duration:.0f}ms): {str(e)}")

            return {"success": False, "result": "", "error": str(e)}

    

    async def _execute_step_rag(self, context: str, original_task: str, history_context: str = "", original_question: str = "") -> dict:

        """执行 RAG 步骤"""

        print(f"[StreamHandler:RAG] ========== 开始执行 ==========")

        print(f"[StreamHandler:RAG] 入参 original_task: {original_task}")

        print(f"[StreamHandler:RAG] 入参 original_question: {original_question}")

        print(f"[StreamHandler:RAG] 入参 context({len(context)}字符): {context}")

        print(f"[StreamHandler:RAG] 入参 history_context({len(history_context)}字符)")

        t0 = time.time()

        try:

            from app.multi_agent.rag_agent import RAGAgent



            agent = RAGAgent()

            result = await agent.execute(

                original_task,

                self.user_context,

                route_context=context,

                history_context=history_context,

                original_question=original_question or original_task,

            )



            duration = (time.time() - t0) * 1000

            print(f"[StreamHandler:RAG] 执行耗时: {duration:.0f}ms")

            print(f"[StreamHandler:RAG] 执行结果: success={result.success}, result_length={len(result.result) if result.result else 0}")

            if result.success:

                print(f"[StreamHandler:RAG] 输出内容: {result.result}")



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

        print(f"[StreamHandler:LLM] 入参 context({len(context)}字符): {context}")

        t0 = time.time()

        try:

            from app.multi_agent.llm_agent import LLMAgent



            agent = LLMAgent()

            result = await agent.execute(context, self.user_context, history_context=history_context)



            duration = (time.time() - t0) * 1000

            print(f"[StreamHandler:LLM] 执行耗时: {duration:.0f}ms")

            print(f"[StreamHandler:LLM] 执行结果: success={result.success}, result_length={len(result.result) if result.result else 0}")

            if result.success:

                print(f"[StreamHandler:LLM] 输出内容: {result.result}")



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

        print(f"[StreamHandler:Tool] 入参 context({len(context)}字符): {context}")

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

                print(f"[StreamHandler:Tool] 输出内容: {str(result.get('answer', ''))}")

            

            return {

                "success": result.get("success", False),

                "result": result.get("answer", ""),

                "error": result.get("error", "")

            }

        except Exception as e:

            duration = (time.time() - t0) * 1000

            print(f"[StreamHandler:Tool] 异常({duration:.0f}ms): {str(e)}")

            return {"success": False, "result": "", "error": str(e)}

    
    async def _extract_params_with_llm(self, tool_name: str, message: str, route_context: dict, history_text: str) -> dict:
        """
        用 LLM 从对话上下文中提取工具参数

        从 Pydantic schema 自动提取完整参数规范（类型、描述、默认值），
        不写死任何映射关系，完全依赖 schema 中的 description 信息。

        Args:
            tool_name: 工具名称
            message: 用户原始消息
            route_context: 路由上下文
            history_text: 历史对话文本

        Returns:
            提取的参数字典
        """
        try:
            from app.tools import TOOL_MAP
            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage

            tool = TOOL_MAP.get(tool_name)
            if not tool or not hasattr(tool, 'args_schema') or not tool.args_schema:
                return {"shop_id": self.user_context.shop_id}

            # 从 Pydantic schema 提取完整参数规范
            schema = tool.args_schema
            schema_json = schema.model_json_schema()
            properties = schema_json.get("properties", {})
            required = schema_json.get("required", [])

            # 构建参数说明（包含 type、必填/可选、默认值、完整 description）
            param_lines = []
            for name, info in properties.items():
                desc = info.get("description", name)
                typ = info.get("type", "string")
                default = info.get("default")
                if name in required:
                    meta = "必填"
                elif default is not None:
                    meta = f"可选，默认: {default}"
                else:
                    meta = "可选，默认: null"
                param_lines.append(f"- {name}: {typ} ({meta}) {desc}")

            tool_desc = getattr(tool, 'description', tool_name)
            understanding = (route_context or {}).get("understanding", "")
            analysis = (route_context or {}).get("analysis", "")

            # 特殊工具的额外提取规则
            extra_rules = ""
            if tool_name in ("refund_approve", "refund_reject"):
                extra_rules = """

退款操作特殊规则:
- 如果用户指定了顾客姓名（如"赵丽颖的退款"），额外提取 _customer_name 字段
- 如果用户指定了多个退款ID（如"拒绝退款9和10"），额外提取 _refund_ids 字段（数组格式）
- 如果用户说"全部拒绝"但没有指定具体ID，_refund_ids 设为 null"""
            elif tool_name == "game_session_checkin":
                extra_rules = """

核销操作特殊规则:
- 如果用户指定了顾客姓名（如"小灰灰的场次"），额外提取 _customer_name 字段
- 如果用户指定了顾客ID，提取 customer_id 字段"""

            prompt = f"""根据对话上下文，提取调用工具所需的参数。

工具: {tool_name}
工具说明: {tool_desc}

参数规范:
{chr(10).join(param_lines)}

提取规则（必须严格遵守）:
1. description 中的 "X=Y" 是值映射关系（如 "pending=处理中" 表示用户说"待处理"时应填 "pending"），必须按映射填值
2. 必填参数必须提取，确实无法确定则填 null
3. 可选参数无法确定时填 null（不要填空字符串 "" 或数字 0）
4. 数字参数填数字（如 20），不要填字符串（如 "20"）
5. 只返回一个 JSON 对象，不要返回任何其他文字
{extra_rules}

对话上下文:
{history_text}

Router 理解: {understanding}
Router 分析: {analysis}

用户消息: {message}"""

            llm = get_chat_llm(temperature=0)
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            # 解析 JSON
            content = response.content.strip()
            if "```json" in content:
                start = content.find("```json") + 7
                end = content.find("```", start)
                content = content[start:end].strip()
            elif "```" in content:
                start = content.find("```") + 3
                end = content.find("```", start)
                content = content[start:end].strip()

            import json
            params = json.loads(content)

            # 清理：安全的类型转换，不破坏合法值
            for key, val in params.items():
                if val is None:
                    continue
                if isinstance(val, str):
                    stripped = val.strip()
                    if stripped in ("", "null", "none", "None"):
                        params[key] = None
                    elif stripped.isdigit():
                        params[key] = int(stripped)
                    else:
                        try:
                            params[key] = float(stripped)
                        except ValueError:
                            pass  # 保持原字符串

            # 根据 schema 类型做转换
            for key, val in params.items():
                if val is None:
                    continue
                expected_type = properties.get(key, {}).get("type")
                if expected_type == "integer" and isinstance(val, str) and val.isdigit():
                    params[key] = int(val)
                elif expected_type == "number" and isinstance(val, str):
                    try:
                        params[key] = float(val)
                    except ValueError:
                        pass
                elif expected_type == "string" and isinstance(val, (int, float)):
                    params[key] = str(val)

            # shop_id 强制覆盖（不可被 LLM 修改）
            params["shop_id"] = self.user_context.shop_id

            # 移除值为 None 的参数（让 Pydantic 使用 schema 中的默认值）
            params = {k: v for k, v in params.items() if v is not None}

            print(f"[StreamHandler:LLMExtract] {tool_name} 提取参数: {params}")
            return params

        except Exception as e:
            print(f"[StreamHandler:LLMExtract] 第1次提取失败: {str(e)}，重试...")
            # 重试：更简洁的 prompt，减少干扰
            try:
                from app.llm import get_chat_llm as _get_llm
                from langchain_core.messages import HumanMessage as _HM
                retry_llm = _get_llm(temperature=0)
                retry_prompt = f"""从用户消息中提取参数，只返回 JSON，不要其他文字。

工具: {tool_name}
用户消息: {message}

返回格式（无法确定的字段填 null）:
{{"shop_id": {self.user_context.shop_id}}}"""

                retry_resp = await retry_llm.ainvoke([_HM(content=retry_prompt)])
                retry_content = retry_resp.content.strip()
                if "{" in retry_content:
                    json_str = retry_content[retry_content.index("{"):retry_content.rindex("}") + 1]
                    import json as _json
                    params = _json.loads(json_str)
                    params["shop_id"] = self.user_context.shop_id
                    # 清理空值
                    params = {k: v for k, v in params.items() if v is not None and v != "" and v != 0}
                    print(f"[StreamHandler:LLMExtract] 重试成功: {params}")
                    return params
            except Exception as e2:
                print(f"[StreamHandler:LLMExtract] 重试也失败: {str(e2)}")

            return {"shop_id": self.user_context.shop_id}

    async def _verify_and_fill_params(self, tool_name: str, params: dict) -> dict:
        """
        验证 LLM 提取的参数，从 DB 补充缺失信息

        Args:
            tool_name: 工具名称
            params: LLM 提取的参数

        Returns:
            验证后的参数（含 _verified, _customer_name, _pending_refunds 等内部字段）
        """
        from app.nl2sql.executor import execute_sql
        from decimal import Decimal

        def convert_decimals(items: list) -> list:
            """将查询结果中的 Decimal 转为 float（JSON 序列化需要）"""
            converted = []
            for item in items:
                converted.append({k: float(v) if isinstance(v, Decimal) else v for k, v in item.items()})
            return converted

        if tool_name in ("refund_approve", "refund_reject"):
            refund_id = params.get("refund_id")
            customer_name = params.get("_customer_name")
            refund_ids = params.get("_refund_ids")  # 列表

            if refund_ids and isinstance(refund_ids, list) and len(refund_ids) > 0:
                # 用户指定了多个ID
                placeholders = ", ".join([str(int(rid)) for rid in refund_ids])
                results = execute_sql(
                    f"SELECT rr.id, rr.refund_amount, c.nickname, rr.reason, rr.status "
                    f"FROM refund_records rr "
                    f"JOIN purchases pu ON rr.purchase_id = pu.id "
                    f"LEFT JOIN customers c ON pu.customer_id = c.id "
                    f"WHERE rr.id IN ({placeholders}) AND pu.shop_id = :sid AND rr.is_deleted = 0",
                    {"sid": params.get("shop_id")}
                )
                pending = [r for r in results if r.get("status") == 1]
                if not pending:
                    params["_verified"] = False
                    params["_error"] = "指定的退款记录不存在或不是待审核状态"
                elif len(pending) == 1:
                    params["refund_id"] = pending[0]["id"]
                    params["_verified"] = True
                    params["_customer_name"] = pending[0].get("nickname", "")
                else:
                    params["_verified"] = False
                    params["_pending_refunds"] = pending
                    params["_multi_select"] = True

            elif refund_id and refund_id != 0:
                # 用户指定了单个ID
                result = execute_sql(
                    "SELECT rr.id, rr.status, c.nickname FROM refund_records rr "
                    "JOIN purchases pu ON rr.purchase_id = pu.id "
                    "LEFT JOIN customers c ON pu.customer_id = c.id "
                    "WHERE rr.id = :id AND pu.shop_id = :sid AND rr.is_deleted = 0",
                    {"id": refund_id, "sid": params.get("shop_id")}
                )
                if result:
                    refund = result[0]
                    params["_verified"] = True
                    params["_customer_name"] = refund.get("nickname", "")
                    params["_refund_status"] = refund.get("status")
                    if refund.get("status") != 1:
                        params["_verified"] = False
                        params["_error"] = f"退款状态不是待审核（当前状态: {refund.get('status')}）"
                else:
                    params["_verified"] = False
                    params["_error"] = f"退款记录 {refund_id} 不存在"

            elif customer_name:
                # 用户指定了顾客名，查询该顾客的待处理退款
                results = execute_sql(
                    "SELECT rr.id, rr.refund_amount, c.nickname, rr.reason "
                    "FROM refund_records rr "
                    "JOIN purchases pu ON rr.purchase_id = pu.id "
                    "LEFT JOIN customers c ON pu.customer_id = c.id "
                    "WHERE pu.shop_id = :sid AND rr.status = 1 AND rr.is_deleted = 0 "
                    "AND c.nickname LIKE :name",
                    {"sid": params.get("shop_id"), "name": f"%{customer_name}%"}
                )
                if not results:
                    params["_verified"] = False
                    params["_error"] = f"没有找到 {customer_name} 的待处理退款"
                elif len(results) == 1:
                    params["refund_id"] = results[0]["id"]
                    params["_verified"] = True
                    params["_customer_name"] = results[0].get("nickname", "")
                else:
                    params["_verified"] = False
                    params["_pending_refunds"] = convert_decimals(results)
                    params["_multi_select"] = True

            else:
                # 什么都没指定，查全部待处理退款
                results = execute_sql(
                    "SELECT rr.id, rr.refund_amount, c.nickname, rr.reason "
                    "FROM refund_records rr "
                    "JOIN purchases pu ON rr.purchase_id = pu.id "
                    "LEFT JOIN customers c ON pu.customer_id = c.id "
                    "WHERE pu.shop_id = :sid AND rr.status = 1 AND rr.is_deleted = 0",
                    {"sid": params.get("shop_id")}
                )
                if not results:
                    params["_verified"] = False
                    params["_error"] = "没有待处理的退款申请"
                elif len(results) == 1:
                    params["refund_id"] = results[0]["id"]
                    params["_verified"] = True
                    params["_customer_name"] = results[0].get("nickname", "")
                else:
                    params["_verified"] = False
                    params["_pending_refunds"] = convert_decimals(results)
                    params["_multi_select"] = True

        elif tool_name == "game_session_checkin":
            customer_id = params.get("customer_id")
            customer_name = params.get("_customer_name")

            if customer_id:
                # 查询该顾客的可用场次
                results = execute_sql(
                    "SELECT cs.id, cs.customer_id, c.nickname, p.name as package_name, cs.session_date "
                    "FROM customer_sessions cs "
                    "JOIN purchases pu ON cs.purchase_id = pu.id "
                    "JOIN packages p ON pu.package_id = p.id "
                    "LEFT JOIN customers c ON cs.customer_id = c.id "
                    "WHERE cs.customer_id = :cid AND cs.shop_id = :sid AND cs.status = 1 AND cs.is_deleted = 0",
                    {"cid": customer_id, "sid": params.get("shop_id")}
                )
                if not results:
                    params["_verified"] = False
                    params["_error"] = "该顾客没有可用的场次"
                elif len(results) == 1:
                    params["customer_session_id"] = results[0]["id"]
                    params["_verified"] = True
                else:
                    params["_verified"] = False
                    params["_pending_items"] = convert_decimals(results)
                    params["_multi_select"] = True
            elif customer_name:
                # 按顾客名查询可用场次
                results = execute_sql(
                    "SELECT cs.id, cs.customer_id, c.nickname, p.name as package_name, cs.session_date "
                    "FROM customer_sessions cs "
                    "JOIN purchases pu ON cs.purchase_id = pu.id "
                    "JOIN packages p ON pu.package_id = p.id "
                    "LEFT JOIN customers c ON cs.customer_id = c.id "
                    "WHERE c.nickname LIKE :name AND cs.shop_id = :sid AND cs.status = 1 AND cs.is_deleted = 0",
                    {"name": f"%{customer_name}%", "sid": params.get("shop_id")}
                )
                if not results:
                    params["_verified"] = False
                    params["_error"] = f"没有找到 {customer_name} 的可用场次"
                elif len(results) == 1:
                    params["customer_session_id"] = results[0]["id"]
                    params["_verified"] = True
                else:
                    params["_verified"] = False
                    params["_pending_items"] = convert_decimals(results)
                    params["_multi_select"] = True
            else:
                params["_verified"] = True

        elif tool_name == "game_session_finish":
            # 查询所有进行中的场次
            results = execute_sql(
                "SELECT gs.id, c.nickname, p.name as package_name, gs.start_time "
                "FROM game_sessions gs "
                "LEFT JOIN customer_sessions cs ON gs.customer_session_id = cs.id "
                "LEFT JOIN purchases pu ON cs.purchase_id = pu.id "
                "LEFT JOIN packages p ON pu.package_id = p.id "
                "LEFT JOIN customers c ON pu.customer_id = c.id "
                "WHERE gs.shop_id = :sid AND gs.status = 1 AND (gs.is_deleted = 0 OR gs.is_deleted IS NULL)",
                {"sid": params.get("shop_id")}
            )
            if not results:
                params["_verified"] = False
                params["_error"] = "当前没有进行中的场次"
            elif len(results) == 1:
                params["game_session_id"] = results[0]["id"]
                params["_verified"] = True
            else:
                params["_verified"] = False
                params["_pending_items"] = convert_decimals(results)
                params["_multi_select"] = True

        else:
            params["_verified"] = True

        return params

    async def _execute_with_agent_loop(self, tool_name: str, message: str, route_context: dict = None, query_context: dict = None) -> dict:
        """
        Agent Loop 方式执行工具（LLM 自主规划参数获取）

        流程：
        1. 构建 prompt（用户消息 + 工具需求 + 可用查询工具 + 查询上下文）
        2. LLM 生成 plan（哪些参数怎么获取）
        3. 执行 plan 中的每一步
        4. 如果需要用户选择 → 返回 select 弹窗
        5. 参数齐全或无法继续 → 调用目标工具

        Args:
            tool_name: 工具名称
            message: 用户原始消息
            route_context: 路由上下文
            query_context: 之前的查询结果（用于多任务场景，避免重复查询）

        Returns:
            {"success": bool, "result": str, "error": str, "confirm_data": dict, "select_data": dict}
        """
        t0 = time.time()
        try:
            from app.tools import TOOL_MAP
            from app.tools.tool_requirements import TOOL_REQUIREMENTS

            tool = TOOL_MAP.get(tool_name)
            if not tool:
                return {"success": False, "result": "", "error": f"工具 {tool_name} 不存在"}

            tool_req = TOOL_REQUIREMENTS.get(tool_name)
            if not tool_req or isinstance(tool_req, str):
                # 没有 Agent Loop 配置，走原有 param_plans 流程
                return await self._execute_with_param_resolution(tool_name, message, route_context)

            # 构建参数描述（包含类型和提取方式）
            params_info = tool_req.get("params", {})
            params_desc_parts = []
            for pname, pinfo in params_info.items():
                ptype = pinfo.get("type", "str")
                pdesc = pinfo.get("description", "")
                pextract = pinfo.get("extract", "first")
                prequired = pinfo.get("required", True)
                extract_desc = {
                    "first": "提取第一个结果",
                    "all_concat": "提取所有结果，逗号拼接",
                    "value": "直接使用值"
                }.get(pextract, "提取第一个结果")
                params_desc_parts.append(f"- {pname} ({ptype}, {'必填' if prequired else '可选'}): {pdesc} | 提取方式: {extract_desc}")

            # 构建 Agent Loop prompt
            history_text = self._get_history_text()
            strategies = tool_req.get("strategies", "")
            fallback = tool_req.get("fallback", "")

            # 构建查询上下文（之前的查询结果）
            query_context_text = ""
            if query_context:
                query_context_text = "\n\n## 之前的查询结果（可直接使用这些数据，不需要重复查询）\n"
                for task_id, result in query_context.items():
                    if result:
                        # 截断过长的结果
                        result_preview = result[:500] + "..." if len(result) > 500 else result
                        query_context_text += f"- 任务{task_id}: {result_preview}\n"

            system_prompt = f"""你是参数解析助手。用户想要执行 {tool_name} 操作，你需要帮他解析出所需的参数。

## 用户消息
{message}

{f"## 对话历史{chr(10)}{history_text}" if history_text else ""}
{query_context_text}

## 工具描述
{tool_req.get('description', tool_name)}

## 工具参数需求
{chr(10).join(params_desc_parts)}

## 获取策略
{strategies}

## 兜底规则
{fallback}

## 输出格式
分析用户消息，规划如何获取每个参数。返回 JSON：

{{
  "thought": "简要分析思路",
  "params": {{
    "param_name": {{
      "value": "直接值（如果能从用户消息中确定，填入具体值）",
      "action": "nl2sql|skip",
      "description": "NL2SQL 查询描述（action=nl2sql 时必填，用自然语言描述查询需求）",
      "on_empty": "select|skip|error"
    }}
  }}
}}

规则：
- 如果用户明确指定了值（如名称、ID、数量），直接填入 value（注意类型：int 填数字，str 填字符串）
- 如果需要查询，action 填 "nl2sql"，description 用自然语言描述查询需求
- 如果无法确定，action 填 "skip"
- on_empty 规则：
  - 可查询参数（ID、名称等）：如果无法确定，on_empty 填 "select"（返回列表让用户选）
  - 自由文本参数（reason、remark、备注等）：on_empty 填 "skip"（留空让工具的 confirm 弹窗让用户填写）
- 不要编造不存在的数据
- 不要为自由文本字段（reason、remark、备注）设置 on_empty="select"
- 不要输出任何解释或 markdown 代码块
- 只返回一个完整的 JSON 对象，所有字符串用双引号，布尔值用小写 true/false"""

            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage

            llm = get_chat_llm(temperature=0)
            resp = await llm.ainvoke([HumanMessage(content=system_prompt)])
            content = resp.content.strip()

            # 解析 LLM 返回的 JSON（带重试）
            plan = None
            max_retries = 2
            for attempt in range(max_retries + 1):
                plan = self._extract_json(content)
                if plan:
                    break
                
                if attempt < max_retries:
                    print(f"[AgentLoop] JSON 解析失败，重试 {attempt + 1}/{max_retries}")
                    retry_prompt = system_prompt + "\n\n【重要】你上次返回的内容不是有效的 JSON。请严格只返回一个 JSON 对象，不要包含任何其他文字、解释或 markdown 代码块。"
                    resp = await llm.ainvoke([HumanMessage(content=retry_prompt)])
                    content = resp.content.strip()
            
            if not plan:
                plan = {"thought": "无法解析", "params": {}}

            print(f"[AgentLoop] {tool_name} plan: {plan}")

            # 执行 plan
            shop_id = self.user_context.shop_id
            final_params = {"shop_id": shop_id}
            params_config = plan.get("params", {})

            for param_name, param_plan in params_config.items():
                # 获取参数的类型和提取方式（从 requirements 中）
                param_info = params_info.get(param_name, {})
                param_type = param_info.get("type", "str")
                extract_mode = param_info.get("extract", "first")

                value = param_plan.get("value")
                action = param_plan.get("action", "skip")
                on_empty = param_plan.get("on_empty", "skip")

                if value is not None and str(value).strip():
                    # 有直接值，进行类型转换
                    final_params[param_name] = self._convert_param_type(value, param_type)
                    print(f"[AgentLoop] {param_name} = {final_params[param_name]}（直接值，类型: {param_type}）")
                    continue

                if action == "nl2sql":
                    # NL2SQL 查询
                    nl2sql_question = param_plan.get("description", "")
                    if nl2sql_question:
                        print(f"[AgentLoop] {param_name} 需要 NL2SQL: {nl2sql_question}")
                        nl2sql_result = await self._execute_step_nl2sql(nl2sql_question, message)
                        if nl2sql_result and nl2sql_result.get("success"):
                            result_text = nl2sql_result.get("result", "")
                            # 根据 extract 模式提取值
                            if extract_mode == "all_concat":
                                extracted_value = self._extract_all_ids_from_nl2sql_result(result_text)
                            else:
                                extracted_value = self._extract_id_from_nl2sql_result(result_text)

                            if extracted_value is not None:
                                # 类型转换
                                final_params[param_name] = self._convert_param_type(extracted_value, param_type)
                                print(f"[AgentLoop] {param_name} = {final_params[param_name]}（NL2SQL 结果，extract={extract_mode}）")
                            else:
                                # 无法提取
                                if on_empty == "select":
                                    return await self._build_agent_loop_select_all(tool_name, param_name, params_config, shop_id)
                        else:
                            # NL2SQL 失败
                            if on_empty == "select":
                                return await self._build_agent_loop_select_all(tool_name, param_name, params_config, shop_id)

                if param_name not in final_params:
                    # 无法确定，根据 on_empty 处理
                    if on_empty == "select":
                        return await self._build_agent_loop_select_all(tool_name, param_name, params_config, shop_id)
                    elif on_empty == "skip":
                        print(f"[AgentLoop] {param_name} 无法确定，留空让工具处理")
                    elif on_empty == "error":
                        return {"success": False, "result": "", "error": f"无法确定参数 {param_name}"}

            # 调用目标工具（不校验 required，缺失的参数由工具的 confirm 弹窗让用户填写）
            print(f"[AgentLoop] 参数解析完成: {final_params}")
            return await self._call_tool_direct(tool, tool_name, message, route_context, override_params=final_params)

        except Exception as e:
            duration = (time.time() - t0) * 1000
            print(f"[AgentLoop] {tool_name} 异常({duration:.0f}ms): {str(e)}")
            import traceback
            traceback.print_exc()
            return {"success": False, "result": "", "error": str(e)}

    def _extract_id_from_nl2sql_result(self, result_text: str):
        """从 NL2SQL 结果中提取第一个 ID"""
        import re
        lines = result_text.strip().split("\n")
        for line in lines:
            # 跳过标题行
            if line.startswith("查询") or line.startswith("找到") or line.startswith("---"):
                continue
            # 匹配纯数字行
            match = re.match(r'^\s*(\d+)\s*$', line.strip())
            if match:
                return int(match.group(1))
        return None

    def _extract_all_ids_from_nl2sql_result(self, result_text: str) -> str:
        """从 NL2SQL 结果中提取所有 ID，逗号拼接为字符串"""
        import re
        ids = []
        lines = result_text.strip().split("\n")
        for line in lines:
            # 跳过标题行
            if line.startswith("查询") or line.startswith("找到") or line.startswith("---"):
                continue
            # 匹配纯数字行
            match = re.match(r'^\s*(\d+)\s*$', line.strip())
            if match:
                ids.append(match.group(1))
        if ids:
            return ",".join(ids)
        return None

    def _convert_param_type(self, value, target_type: str):
        """将值转换为目标类型"""
        if value is None:
            return None

        if target_type == "int":
            try:
                return int(value)
            except (ValueError, TypeError):
                # 如果是 "1,2,3" 格式的字符串，取第一个
                if isinstance(value, str) and "," in value:
                    return int(value.split(",")[0].strip())
                return value
        elif target_type == "str":
            return str(value)
        else:
            return value

    def _extract_json(self, content: str):
        """从 LLM 输出中提取 JSON 对象（支持多种格式）"""
        import json as _json
        
        if not content:
            return None
        
        # 1. 尝试直接解析
        try:
            return _json.loads(content)
        except _json.JSONDecodeError:
            pass
        
        # 2. 尝试提取 ```json ``` 代码块
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                try:
                    return _json.loads(content[start:end].strip())
                except _json.JSONDecodeError:
                    pass
        
        # 3. 尝试提取 ``` ``` 代码块
        if "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                try:
                    return _json.loads(content[start:end].strip())
                except _json.JSONDecodeError:
                    pass
        
        # 4. 尝试提取第一个 { 到最后一个 }
        if "{" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            try:
                return _json.loads(content[start:end])
            except _json.JSONDecodeError:
                pass
        
        return None

    def _build_agent_loop_select(self, tool_name: str, param_name: str, result_text: str, params_config: dict) -> dict:
        """构建 Agent Loop 的选择弹窗（从 NL2SQL 结果中选择）"""
        display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)

        # 解析结果为选项
        options = []
        lines = result_text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("查询") or line.startswith("找到"):
                continue
            # 尝试解析 "| id | name |" 格式
            if "|" in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2 and parts[0].isdigit():
                    options.append({"value": parts[0], "label": " - ".join(parts[1:])})
            # 尝试解析 "id: xxx, name: xxx" 格式
            elif ":" in line:
                parts = line.split(",")
                if len(parts) >= 2:
                    id_part = parts[0].split(":")[-1].strip()
                    name_part = parts[1].split(":")[-1].strip()
                    if id_part.isdigit():
                        options.append({"value": id_part, "label": name_part})

        if not options:
            options.append({"value": "", "label": f"无可用数据: {result_text[:100]}"})

        return {
            "success": True,
            "result": "",
            "select_data": {
                "type": "select",
                "tool_name": tool_name,
                "title": f"选择{param_name}",
                "message": f"请选择{param_name}：",
                "items": [{"id": opt["value"], "name": opt["label"]} for opt in options],
                "fields": [],
                "action": tool_name,
                "params": {"shop_id": self.user_context.shop_id},
            },
            "error": "",
        }

    async def _build_agent_loop_select_all(self, tool_name: str, param_name: str, params_config: dict, shop_id: int) -> dict:
        """查询所有选项并返回选择弹窗"""
        display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)

        # 根据参数名确定查询方式
        if param_name == "coupon_id":
            # 查询所有优惠券
            from app.nl2sql.executor import execute_sql
            results = execute_sql(
                "SELECT id, name, type, value, remain_stock FROM coupons WHERE shop_id = :sid AND is_deleted=0 AND is_active=1",
                {"sid": shop_id}
            )
            if results:
                options = [{"value": str(r["id"]), "label": f"{r['name']} (¥{r['value']}, 库存{r['remain_stock']})"} for r in results]
            else:
                return {"success": False, "result": "", "error": "当前没有可用的优惠券"}

        elif param_name == "customer_ids":
            # 查询所有顾客
            from app.nl2sql.executor import execute_sql
            results = execute_sql(
                "SELECT id, nickname, phone FROM customers WHERE shop_id = :sid AND (is_deleted=0 OR is_deleted IS NULL)",
                {"sid": shop_id}
            )
            if results:
                options = [{"value": str(r["id"]), "label": f"{r['nickname']} ({r['phone'] or '无手机'})"} for r in results]
            else:
                return {"success": False, "result": "", "error": "当前没有顾客"}

        elif param_name == "material_id":
            # 查询所有物料
            from app.nl2sql.executor import execute_sql
            results = execute_sql(
                "SELECT m.id, m.name, m.unit, inv.quantity FROM materials m LEFT JOIN inventory inv ON m.id = inv.material_id WHERE m.shop_id = :sid AND (m.is_deleted=0 OR m.is_deleted IS NULL)",
                {"sid": shop_id}
            )
            if results:
                options = [{"value": str(r["id"]), "label": f"{r['name']} (库存: {r['quantity'] or 0} {r['unit']})"} for r in results]
            else:
                return {
                    "success": False,
                    "result": "",
                    "error": "当前没有物料，请先到后台【物料管理】页面添加物料"
                }

        elif param_name == "refund_id":
            # 查询所有待处理退款（通过 purchases 表关联 customers）
            from app.nl2sql.executor import execute_sql
            results = execute_sql(
                "SELECT rr.id, c.nickname, rr.refund_amount FROM refund_records rr "
                "JOIN purchases p ON rr.purchase_id = p.id "
                "JOIN customers c ON p.customer_id = c.id "
                "WHERE rr.shop_id = :sid AND rr.status=1 AND (rr.is_deleted=0 OR rr.is_deleted IS NULL)",
                {"sid": shop_id}
            )
            if results:
                options = [{"value": str(r["id"]), "label": f"{r['nickname']} - ¥{r['refund_amount']}"} for r in results]
            else:
                return {"success": False, "result": "", "error": "当前没有待处理的退款"}

        elif param_name == "feedback_id":
            # 查询所有待回复评价
            from app.nl2sql.executor import execute_sql
            results = execute_sql(
                "SELECT f.id, c.nickname, LEFT(f.content, 30) as content FROM feedbacks f LEFT JOIN customers c ON f.customer_id = c.id WHERE f.shop_id = :sid AND f.status=1 AND (f.is_deleted=0 OR f.is_deleted IS NULL)",
                {"sid": shop_id}
            )
            if results:
                options = [{"value": str(r["id"]), "label": f"{r['nickname']}: {r['content']}"} for r in results]
            else:
                return {"success": False, "result": "", "error": "当前没有待回复的评价"}

        elif param_name == "game_session_id" or param_name == "customer_session_id":
            # 查询所有进行中的场次
            from app.nl2sql.executor import execute_sql
            results = execute_sql(
                "SELECT gs.id, c.nickname, gs.start_time FROM game_sessions gs LEFT JOIN customers c ON gs.customer_id = c.id WHERE gs.shop_id = :sid AND gs.status=1 AND (gs.is_deleted=0 OR gs.is_deleted IS NULL)",
                {"sid": shop_id}
            )
            if results:
                options = [{"value": str(r["id"]), "label": f"{r['nickname']} - {r['start_time']}"} for r in results]
            else:
                return {"success": False, "result": "", "error": "当前没有进行中的场次"}

        else:
            return {"success": False, "result": "", "error": f"无法自动查询参数 {param_name}"}

        # 获取参数的中文描述
        from app.tools.tool_requirements import TOOL_REQUIREMENTS
        tool_req = TOOL_REQUIREMENTS.get(tool_name, {})
        param_desc = tool_req.get("params", {}).get(param_name, {}).get("description", param_name)

        return {
            "success": True,
            "result": "",
            "select_data": {
                "type": "select",
                "tool_name": tool_name,
                "title": f"选择{param_desc}",
                "message": f"请选择{param_desc}：",
                "items": [{"id": opt["value"], "name": opt["label"]} for opt in options],
                "fields": [],
                "action": tool_name,
                "params": {"shop_id": shop_id},
            },
            "error": "",
        }

    async def _execute_with_param_resolution(self, tool_name: str, message: str, route_context: dict = None) -> dict:
        """
        带参数解析的工具执行流程

        1. LLM 提取中间变量（名称/标记，不是 ID）
        2. 检查参数计划，确定缺失参数
        3. 用查询工具解析名称→ID（支持 derived 推导、dynamic_tool_by 动态选择）
        4. 参数齐全后调用工具返回 confirm

        Args:
            tool_name: 工具名称
            message: 用户原始消息
            route_context: 路由上下文

        Returns:
            {"success": bool, "result": str, "error": str, "confirm_data": dict, "select_data": dict}
        """
        t0 = time.time()
        try:
            from app.tools import TOOL_MAP
            from app.tools.param_plans import TOOL_PARAM_PLANS

            tool = TOOL_MAP.get(tool_name)
            if not tool:
                return {"success": False, "result": "", "error": f"工具 {tool_name} 不存在"}

            param_plan = TOOL_PARAM_PLANS.get(tool_name)
            if not param_plan:
                return await self._call_tool_direct(tool, tool_name, message, route_context)

            # Step 0: 注入 pre_filled 参数的默认值（从工具 schema 获取）
            shop_id = self.user_context.shop_id
            final_params = {"shop_id": shop_id}
            for pre_filled_name in param_plan.get("pre_filled", []):
                if pre_filled_name == "shop_id":
                    continue
                # 从工具 schema 获取默认值
                try:
                    tool_schema = tool.args_schema.model_json_schema() if hasattr(tool, 'args_schema') and tool.args_schema else {}
                    prop = tool_schema.get("properties", {}).get(pre_filled_name, {})
                    default_val = prop.get("default")
                    if default_val is not None:
                        final_params[pre_filled_name] = default_val
                except Exception:
                    pass

            # Step 1: 用 LLM 从用户消息中提取中间变量（名称/标记 + user_input 值）
            extract_fields = []
            for param_name, query_info in param_plan.get("from_query", {}).items():
                extract_field = query_info.get("extract_field", param_name)
                desc = query_info.get("description", param_name)
                extract_fields.append((extract_field, f"{desc}（名称/ALL/列表）"))
                # 自动追加排除字段
                extract_fields.append((f"exclude_{extract_field}_ids", f"排除的{desc}数字ID列表（数组，如[29,39,44]）"))
                extract_fields.append((f"exclude_{extract_field}_names", f"排除的{desc}名称列表（数组，如[\"张三\",\"李四\"]）"))

            # user_input 字段也加入提取范围（可选，提取到则直接填入）
            for input_field in param_plan.get("user_input", []):
                extract_fields.append((input_field, input_field))

            resolution_prompt_parts = []
            for field_name, desc in extract_fields:
                resolution_prompt_parts.append(f"- {field_name}: {desc}")

            history_text = self._get_history_text()
            resolution_prompt = f"""从用户消息中提取以下信息，返回 JSON。

用户消息: {message}
{f"对话历史: {history_text}" if history_text else ""}

需要提取的信息:
{chr(10).join(resolution_prompt_parts)}

规则:
- 名称类字段：提取文字描述（如"兑换券"、"石膏娃娃"），不是数字 ID
- 数量/金额类字段：提取数字（如"100"、"50"）
- 如果用户说"所有"/"全部"/"全部顾客"等，标记为 "ALL"
- 如果用户说"除了X、Y之外"：
  - 如果排除的是数字ID，填入 exclude_xxx_ids 数组
  - 如果排除的是名称（如"张三"），填入 exclude_xxx_names 数组
  - 主字段仍填 "ALL"
- 如果用户指定了多人（如"张三和李四"、"张三、李四、王五"），主字段填数组 ["张三","李四","王五"]
- 如果从对话历史中能找到排除信息（如之前报错提到的ID），提取到 exclude 数组
- 如果无法确定，填 null
- 只返回 JSON，key 是上面的字段名"""

            from app.llm import get_chat_llm
            from langchain_core.messages import HumanMessage

            llm = get_chat_llm(temperature=0)
            resp = await llm.ainvoke([HumanMessage(content=resolution_prompt)])
            content = resp.content.strip()
            if "{" in content:
                json_str = content[content.index("{"):content.rindex("}") + 1]
                import json as _json
                resolved_names = _json.loads(json_str)
            else:
                resolved_names = {}

            print(f"[ParamResolution] LLM 提取中间变量: {resolved_names}")

            # Step 2: 确定缺失参数 + 处理 derived
            # 缓存查询结果，避免同一查询工具重复调用
            query_cache = {}
            missing_names = []  # 需要解析名称的参数

            for param_name, query_info in param_plan.get("from_query", {}).items():
                if query_info.get("derived_from"):
                    # derived 参数：从已有查询结果中推导，稍后处理
                    continue
                extract_field = query_info.get("extract_field", param_name)
                extracted_name = resolved_names.get(extract_field)
                if extracted_name:
                    missing_names.append((param_name, query_info, extracted_name))
                else:
                    # LLM 也没提取到，返回选择框
                    all_items = await self._query_tool_items(query_info["query_tool"], shop_id)
                    if not all_items:
                        return {"success": False, "result": "", "error": f"没有可用的{query_info.get('description', param_name)}"}
                    return self._build_select_response(tool_name, param_plan, param_name, all_items)

            # Step 3: 用查询工具解析名称→ID（支持排除、多值）
            for param_name, query_info, extracted_name in missing_names:
                # 确定实际查询工具（支持 dynamic_tool_by）
                actual_query_tool = query_info["query_tool"]
                if query_info.get("dynamic_tool_by"):
                    dynamic_field = query_info["dynamic_tool_by"]
                    dynamic_value = final_params.get(dynamic_field) or resolved_names.get(dynamic_field)
                    if dynamic_value == "staff":
                        actual_query_tool = "query_staff_list"

                extra_filter = query_info.get("extra_filter", {})
                extract_field = query_info.get("extract_field", param_name)

                if isinstance(extracted_name, str) and extracted_name.upper() == "ALL":
                    # === ALL 模式：查全部 ===
                    cache_key = f"{actual_query_tool}:ALL:{str(extra_filter)}"
                    if cache_key in query_cache:
                        all_items = query_cache[cache_key]
                    else:
                        all_items = await self._query_tool_items(actual_query_tool, shop_id, extra_filter=extra_filter or None)
                        query_cache[cache_key] = all_items

                    if not all_items:
                        return {"success": False, "result": "", "error": f"没有可用的{query_info.get('description', param_name)}"}

                    # 应用排除
                    all_items = await self._apply_exclusions(all_items, resolved_names, extract_field, actual_query_tool, shop_id)

                    if not all_items:
                        return {"success": False, "result": "", "error": f"排除后没有剩余的{query_info.get('description', param_name)}"}

                    if query_info.get("concat"):
                        all_ids = [str(item.get("id", "")) for item in all_items]
                        final_params[param_name] = ",".join(all_ids)
                    else:
                        final_params[param_name] = all_items[0].get("id")

                    # 缓存 ALL 查询结果供 derived 使用
                    query_cache[f"_all_{actual_query_tool}"] = all_items

                elif isinstance(extracted_name, list):
                    # === 多值模式：分别查询每个名称，合并结果 ===
                    all_matched_items = []
                    for single_name in extracted_name:
                        if not single_name or not str(single_name).strip():
                            continue
                        items = await self._query_tool_by_name(actual_query_tool, shop_id, str(single_name).strip(), extra_filter=extra_filter or None)
                        if items:
                            all_matched_items.extend(items)

                    if not all_matched_items:
                        return {"success": False, "result": "", "error": f"没有找到匹配的{query_info.get('description', param_name)}"}

                    # 应用排除
                    all_matched_items = await self._apply_exclusions(all_matched_items, resolved_names, extract_field, actual_query_tool, shop_id)

                    if not all_matched_items:
                        return {"success": False, "result": "", "error": f"排除后没有剩余的{query_info.get('description', param_name)}"}

                    if query_info.get("concat"):
                        all_ids = [str(item.get("id", "")) for item in all_matched_items]
                        final_params[param_name] = ",".join(all_ids)
                    else:
                        final_params[param_name] = all_matched_items[0].get("id")

                else:
                    # === 单值模式：按名称查询 ===
                    cache_key = f"{actual_query_tool}:{extracted_name}:{str(extra_filter)}"
                    if cache_key in query_cache:
                        items = query_cache[cache_key]
                    else:
                        items = await self._query_tool_by_name(actual_query_tool, shop_id, extracted_name, extra_filter=extra_filter or None)
                        query_cache[cache_key] = items

                    if not items:
                        return {"success": False, "result": "", "error": f"没有找到名为'{extracted_name}'的{query_info.get('description', '')}"}
                    elif len(items) == 1:
                        final_params[param_name] = items[0].get("id")
                        # 缓存单条结果供 derived 使用
                        query_cache[f"_single_{actual_query_tool}"] = items[0]
                    else:
                        # 多条匹配，返回选择框
                        return self._build_select_response(tool_name, param_plan, param_name, items)

            # Step 4: 处理 derived 参数
            for param_name, query_info in param_plan.get("from_query", {}).items():
                if not query_info.get("derived_from"):
                    continue
                source_param = query_info["derived_from"]
                derived_field = query_info.get("derived_field", param_name)

                # 从缓存的查询结果中取值
                source_query_tool = param_plan["from_query"].get(source_param, {}).get("query_tool", "")
                single_key = f"_single_{source_query_tool}"
                all_key = f"_all_{source_query_tool}"

                if single_key in query_cache:
                    # 单条结果，直接取
                    item = query_cache[single_key]
                    final_params[param_name] = item.get(derived_field) or item.get(derived_field.split(".")[-1])
                elif all_key in query_cache:
                    # ALL 结果，取第一条
                    items = query_cache[all_key]
                    if items:
                        final_params[param_name] = items[0].get(derived_field) or items[0].get(derived_field.split(".")[-1])

                if not final_params.get(param_name):
                    return {"success": False, "result": "", "error": f"无法推导参数 {param_name}"}

            # Step 4.5: 处理 user_input（LLM 已提取则填入，否则留给 confirm 弹窗）
            for input_field in param_plan.get("user_input", []):
                extracted_value = resolved_names.get(input_field)
                if extracted_value is not None and str(extracted_value).strip():
                    final_params[input_field] = extracted_value
                    print(f"[ParamResolution] user_input 已提取: {input_field}={extracted_value}")

            # Step 5: 参数齐全，调用工具
            print(f"[ParamResolution] 参数解析完成: {final_params}")
            return await self._call_tool_direct(tool, tool_name, message, route_context, override_params=final_params)

        except Exception as e:
            duration = (time.time() - t0) * 1000
            print(f"[ParamResolution] 异常({duration:.0f}ms): {str(e)}")
            return {"success": False, "result": "", "error": str(e)}

    async def _query_tool_items(self, query_tool_name: str, shop_id: int, extra_filter: dict = None) -> list:
        """查询工具获取所有记录（返回 id + name + extra_fields）"""
        try:
            from app.nl2sql.executor import execute_sql
            from app.tools.param_plans import QUERY_TOOL_FILTERS
            filter_info = QUERY_TOOL_FILTERS.get(query_tool_name, {})
            base_from = filter_info.get("base_from", "")
            id_field = filter_info.get("id_field", "id")
            display_field = filter_info.get("display_field", "name")
            extra_fields = filter_info.get("extra_fields", [])
            if not base_from:
                return []

            # 构建 SELECT 子句
            select_parts = [f"{id_field} as id", f"{display_field} as name"]
            for ef in extra_fields:
                select_parts.append(ef)
            select_clause = ", ".join(select_parts)

            # 构建 WHERE 子句
            main_table = base_from.split()[0]
            where_parts = [f"{main_table}.shop_id = :sid"]
            where_parts.append(f"({main_table}.is_deleted = 0 OR {main_table}.is_deleted IS NULL)")

            # 应用 extra_filter
            if extra_filter:
                for field, value in extra_filter.items():
                    where_parts.append(f"{field} = :ef_{field}")

            where_clause = " AND ".join(where_parts)
            sql = f"SELECT {select_clause} FROM {base_from} WHERE {where_clause}"

            params = {"sid": shop_id}
            if extra_filter:
                for field, value in extra_filter.items():
                    params[f"ef_{field}"] = value

            results = execute_sql(sql, params)
            return results or []
        except Exception as e:
            print(f"[ParamResolution] 查询 {query_tool_name} 失败: {str(e)}")
            return []

    async def _query_tool_by_name(self, query_tool_name: str, shop_id: int, name: str, extra_filter: dict = None) -> list:
        """按名称查询工具获取匹配记录"""
        try:
            from app.nl2sql.executor import execute_sql
            from app.tools.param_plans import QUERY_TOOL_FILTERS
            filter_info = QUERY_TOOL_FILTERS.get(query_tool_name, {})
            base_from = filter_info.get("base_from", "")
            id_field = filter_info.get("id_field", "id")
            display_field = filter_info.get("display_field", "name")
            extra_fields = filter_info.get("extra_fields", [])
            if not base_from:
                return []

            # 构建 SELECT 子句
            select_parts = [f"{id_field} as id", f"{display_field} as name"]
            for ef in extra_fields:
                select_parts.append(ef)
            select_clause = ", ".join(select_parts)

            # 构建 WHERE 子句
            main_table = base_from.split()[0]
            where_parts = [f"{main_table}.shop_id = :sid"]
            where_parts.append(f"({main_table}.is_deleted = 0 OR {main_table}.is_deleted IS NULL)")
            where_parts.append(f"{display_field} LIKE :name")

            # 应用 extra_filter
            if extra_filter:
                for field, value in extra_filter.items():
                    where_parts.append(f"{field} = :ef_{field}")

            where_clause = " AND ".join(where_parts)
            sql = f"SELECT {select_clause} FROM {base_from} WHERE {where_clause}"

            params = {"sid": shop_id, "name": f"%{name}%"}
            if extra_filter:
                for field, value in extra_filter.items():
                    params[f"ef_{field}"] = value

            results = execute_sql(sql, params)
            return results or []
        except Exception as e:
            print(f"[ParamResolution] 按名称查询 {query_tool_name} 失败: {str(e)}")
            return []

    async def _apply_exclusions(self, items: list, resolved_names: dict, extract_field: str, query_tool_name: str, shop_id: int) -> list:
        """从结果列表中排除指定项（支持按 ID 排除和按名称排除）"""
        if not items:
            return items

        exclude_ids = resolved_names.get(f"exclude_{extract_field}_ids", []) or []
        exclude_names = resolved_names.get(f"exclude_{extract_field}_names", []) or []

        # 如果有按名称排除，先查出这些名称的 ID
        if exclude_names:
            for name in exclude_names:
                if name and str(name).strip():
                    excluded_items = await self._query_tool_by_name(query_tool_name, shop_id, str(name).strip())
                    for item in excluded_items:
                        item_id = item.get("id")
                        if item_id is not None and item_id not in exclude_ids:
                            exclude_ids.append(item_id)

        # 按 ID 排除（支持 int 和 str 比较）
        if exclude_ids:
            exclude_set = set(str(eid) for eid in exclude_ids)
            original_count = len(items)
            items = [item for item in items if str(item.get("id")) not in exclude_set]
            excluded_count = original_count - len(items)
            if excluded_count > 0:
                print(f"[ParamResolution] 已排除 {excluded_count} 条记录，剩余 {len(items)} 条")

        return items

    def _build_select_response(self, tool_name: str, param_plan: dict, param_name: str, items: list) -> dict:
        """构建 select 弹窗响应（返回 select_data，前端渲染 SelectCard）"""
        display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
        desc = param_plan['from_query'][param_name].get('description', param_name)

        # 构建附带的 user_input 字段（如 reason、reply_content）
        fields = []
        for input_field in param_plan.get("user_input", []):
            fields.append({
                "name": input_field,
                "type": "input",
                "label": input_field,
                "required": True,
                "placeholder": f"请输入{input_field}",
            })

        return {
            "success": True,
            "result": "",
            "select_data": {
                "type": "select",
                "tool_name": tool_name,
                "title": param_plan.get("confirm_template", {}).get("title", f"选择{desc}"),
                "message": param_plan.get("confirm_template", {}).get("message", f"请选择{desc}："),
                "items": items,       # 查询结果列表（含 id, name 等）
                "fields": fields,     # 附带的用户输入字段
                "action": tool_name,
                "params": {"shop_id": self.user_context.shop_id},
            },
            "error": "",
        }

    async def _call_tool_direct(self, tool, tool_name: str, message: str, route_context: dict = None, override_params: dict = None) -> dict:
        """直接调用工具（最终调用点）"""
        if not tool:
            return {"success": False, "result": "", "error": f"工具 {tool_name} 不存在"}
        t0 = time.time()
        try:
            # 构建参数
            if override_params:
                tool_args = override_params
            else:
                tool_args = self._build_tool_args(tool_name, message, route_context)

            # 注入 token 和 operator_id（Java 后端调用需要）
            if self.user_context and self.user_context.token:
                tool_args.setdefault("token", self.user_context.token)
            if self.user_context and self.user_context.user_id:
                tool_args.setdefault("operator_id", self.user_context.user_id)

            print(f"[ToolDirect] 调用 {tool_name}，参数: {tool_args}")
            answer = await asyncio.to_thread(tool.invoke, tool_args)

            duration = (time.time() - t0) * 1000
            print(f"[ToolDirect] {tool_name} 执行耗时: {duration:.0f}ms")
            print(f"[ToolDirect] {tool_name} 返回: {str(answer)}")

            if isinstance(answer, dict) and answer.get("type") == "confirm":
                return {"success": True, "result": str(answer), "confirm_data": answer, "error": ""}
            if isinstance(answer, dict) and answer.get("type") == "error":
                return {"success": False, "result": "", "error": answer.get("message", "操作失败")}
            return {"success": True, "result": str(answer), "error": ""}
        except Exception as e:
            duration = (time.time() - t0) * 1000
            print(f"[ToolDirect] {tool_name} 异常({duration:.0f}ms): {str(e)}")
            return {"success": False, "result": "", "error": str(e)}

    async def _execute_tool_direct(self, tool_name: str, message: str, route_context: dict = None) -> dict:
        """
        直接调用 TOOL_MAP 中的工具（不经过 AgentLoop）

        流程：
        1. 有 TOOL_REQUIREMENTS → 走 Agent Loop（LLM 自主规划参数获取）
        2. 有 TOOL_PARAM_PLANS → 走参数解析流程（LLM 提取名称 → 查询工具解析）
        3. 都没有 → 直接调用工具

        Args:
            tool_name: 工具名称
            message: 用户消息
            route_context: 路由上下文

        Returns:
            {"success": bool, "result": str, "error": str, "confirm_data": dict}
        """
        # 优先检查是否有 Agent Loop 配置
        from app.tools.tool_requirements import TOOL_REQUIREMENTS
        if tool_name in TOOL_REQUIREMENTS:
            return await self._execute_with_agent_loop(tool_name, message, route_context)

        # 检查工具是否有参数解析计划
        from app.tools.param_plans import TOOL_PARAM_PLANS
        if tool_name in TOOL_PARAM_PLANS:
            # 有参数解析计划，走 LLM 编排流程
            return await self._execute_with_param_resolution(tool_name, message, route_context)

        # 没有配置，直接调用工具
        from app.tools import TOOL_MAP
        tool = TOOL_MAP.get(tool_name)
        if not tool:
            # 查询工具找不到时，fallback 到 NL2SQL
            if tool_name.startswith("query_"):
                print(f"[StreamHandler] 查询工具 {tool_name} 不存在，fallback 到 NL2SQL")
                return await self._execute_step_nl2sql(f"查询: {message}", message)
            return {"success": False, "result": "", "error": f"工具 {tool_name} 不存在"}
        return await self._call_tool_direct(tool, tool_name, message, route_context)

    def _is_valid_result(self, result: str, action: str) -> bool:

        """

        检查结果是否有效

        

        Args:

            result: 执行结果

            action: 原始任务

        

        Returns:

            是否有效

        """

        if not result or len(result.strip()) < 2:

            return False

        

        # 空结果关键词（查询成功但没有数据，这是有效结果）

        empty_result_keywords = [

            "查询结果为空", "没有找到", "无数据", "无记录", "为空",

            "暂无数据", "没有相关", "未找到", "无匹配",

        ]

        result_lower = result.lower()

        for keyword in empty_result_keywords:

            if keyword in result:

                print(f"[StreamHandler] 空结果（有效）: {keyword}")

                return True

        

        # 拒绝性回答关键词

        rejection_keywords = [

            "无法提供", "无法获取", "无法查询", "无法回答", "无法为您",

            "不是我能", "超出我的", "不支持此",

            "sorry", "cannot", "can't",

        ]

        for keyword in rejection_keywords:

            if keyword in result_lower:

                print(f"[StreamHandler] 结果包含拒绝性关键词: {keyword}")

                return False

        

        return True

        

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

                result = await self._execute_step_rag(action, original_task, history_context)

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



            # 构建完整 Prompt（system_prompts 作为 SystemMessage，最高优先级）

            system_prompt, user_prompt = build_summarize_prompt(

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



            response = await llm.ainvoke([

                SystemMessage(content=system_prompt),

                HumanMessage(content=user_prompt),

            ])

            return response.content

        except Exception as e:

            print(f"[StreamHandler] 汇总失败: {str(e)}")

            # 降级：直接返回成功步骤的结果

            success_results = [r.get("result", "") for r in step_results if r.get("success") and r.get("result")]

            return "\n\n".join(success_results) if success_results else "抱歉，处理过程中出现问题，请稍后重试。"

    async def _final_summarize_stream(
        self,
        user_message: str,
        understanding: str,
        analysis: str,
        plan: list,
        step_results: list,
        history_context: str,
    ):
        """
        最终汇总步骤（流式输出）
        
        使用 LLM 流式调用，逐步 yield SSE 事件，让用户更快看到回答。
        
        Args:
            user_message: 用户原始消息
            understanding: Router 对问题的理解
            analysis: Router 的分析
            plan: 执行计划
            step_results: 每步结果
            history_context: 历史上下文
        
        Yields:
            SSE 事件（answer 类型）
        """
        try:
            from app.llm import get_chat_llm
            from app.common.system_prompts import build_summarize_prompt
            from langchain_core.messages import SystemMessage, HumanMessage

            llm = get_chat_llm()

            # 构建完整 Prompt
            system_prompt, user_prompt = build_summarize_prompt(
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

            # 流式调用 LLM
            async for chunk in llm.astream([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]):
                if chunk.content:
                    yield self._format_sse("answer", chunk.content, "回答生成", done=False)

        except Exception as e:
            print(f"[StreamHandler] 流式汇总失败: {str(e)}")
            # 降级：使用非流式方法
            try:
                summary = await self._final_summarize(
                    user_message, understanding, analysis, plan, step_results, history_context
                )
                yield self._format_sse("answer", summary, "回答")
            except Exception as e2:
                yield self._format_sse("answer", "抱歉，处理过程中出现问题，请稍后重试。", "回答")

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

                yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

        except Exception as e:

            print(f"[StreamHandler] LLM 处理失败: {str(e)}")

            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"

            self._ai_response_parts.append(friendly_msg)

            self._ai_response_data_type = "text"

            yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

    

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

                    yield self._format_sse("error", "抱歉，处理过程中出现问题，请稍后重试。", "错误")

                    yield self._format_sse("done", "", "完成", done=True)

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
        try:
            await supervisor_task
        except asyncio.CancelledError:
            print("[StreamHandler] Supervisor 任务被取消")
            return

        # 记录执行结果

        if trace and final_result:

            create_span(trace, "multi_agent_result", {

                "success": final_result.success,

                "confidence": final_result.confidence,

                "result_length": len(final_result.result) if final_result.result else 0,

            })

        

        
        # 输出最终结果
        if final_result and final_result.success:
            # 检查是否有批量确认需求
            metadata = final_result.metadata or {}
            if metadata.get("batch_confirm"):
                # 有操作需要确认，输出 batch_confirm SSE 事件
                batch_confirms = metadata["batch_confirm"]
                batch_data = {
                    "type": "batch_confirm",
                    "title": "确认执行以下操作",
                    "operations": batch_confirms,
                    "buttons": [
                        {"type": "confirm_all", "label": "全部确认"},
                        {"type": "cancel", "label": "取消"},
                    ],
                }
                # 保存到 session
                if self.session_id:
                    try:
                        from app.rag.session import get_session_manager
                        session_mgr = get_session_manager()
                        ops_desc_parts = []
                        for op in batch_confirms:
                            tool_name = op.get("tool_name", op.get("action", ""))
                            display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
                            title = op.get("title", display_name)
                            details = op.get("details", {})
                            detail_str = "、".join([f"{k}:{v}" for k, v in details.items()]) if details else ""
                            ops_desc_parts.append(f"{title}（{detail_str}）" if detail_str else title)
                        ops_desc = "；".join(ops_desc_parts)
                        session_mgr.add_message(self.session_id, "assistant", f"【待确认操作】{ops_desc}")
                    except Exception as e:
                        print(f"[StreamHandler] 保存批量确认消息失败: {str(e)}")
                yield self._format_sse("batch_confirm", batch_data, "批量确认")
                yield self._format_sse("done", "", "完成", done=True)
                return
            
            # 检查是否有选择弹窗需求
            if metadata.get("select_data"):
                select_data = metadata["select_data"]
                yield self._format_sse("select", select_data, "选择")
                yield self._format_sse("done", "", "完成", done=True)
                return
            
            # 提取子任务原始结果

            raw_results = final_result.metadata.get("raw_results", []) if final_result.metadata else []



            yield self._format_sse("processing", "正在汇总分析结果...", "汇总")



            # 构建历史上下文

            history_context = self._build_history_context()



            # 使用统一的 _final_summarize_stream（流式输出）
            async for sse_event in self._final_summarize_stream(
                user_message=message,
                understanding="",
                analysis="",
                plan=[],
                step_results=raw_results,
                history_context=history_context,
            ):
                yield sse_event

            self._ai_response_parts.append("")
            self._ai_response_data_type = "text"

        else:

            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"

            self._ai_response_parts.append(friendly_msg)

            self._ai_response_data_type = "text"

            yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)
        
        # 确保 Supervisor 任务被取消（如果还在运行）
        if not supervisor_task.done():
            supervisor_task.cancel()
            try:
                await supervisor_task
            except asyncio.CancelledError:
                pass
            print("[StreamHandler] Supervisor 任务已取消")
    
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

                

                yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

            

        except Exception as e:

            print(f"[StreamHandler] RAG 处理失败: {str(e)}")

            

            friendly_msg = "抱歉，知识检索出现问题，请稍后重试。"

            self._ai_response_parts.append(friendly_msg)

            self._ai_response_data_type = "text"

            

            yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

    

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

                

                yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

        

        except Exception as e:

            # 异常：友好提示，不暴露错误细节

            print(f"[StreamHandler] NL2SQL 异常: {str(e)}")  # 只在控制台记录

            

            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"

            self._ai_response_parts.append(friendly_msg)

            self._ai_response_data_type = "text"

            

            yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

    

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

                yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

        except Exception as e:

            print(f"[StreamHandler] LLM 处理失败: {str(e)}")

            friendly_msg = "抱歉，处理过程中出现问题，请稍后重试。"

            self._ai_response_parts.append(friendly_msg)

            self._ai_response_data_type = "text"

            yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

    

    async def _process_tool(self, message: str, trace, route_context: dict = None, route_info: str = "", history_context: str = "") -> AsyncGenerator[str, None]:

        """

        处理 Tool 任务

        

        优先使用 Router 指定的 tool_name 直接调用工具，

        如果没有 tool_name 则 fallback 到 AgentLoop。

        """

        yield self._format_sse("processing", "正在调用工具...", "工具调用")

        

        # 优先：Router 指定了具体 tool_name，直接调用

        tool_name = (route_context or {}).get("tool_name", "")

        if tool_name:

            print(f"[StreamHandler] Router 指定工具: {tool_name}")

            try:

                from app.tools import TOOL_MAP

                tool = TOOL_MAP.get(tool_name)

                if not tool:

                    print(f"[StreamHandler] 工具 {tool_name} 不存在，fallback 到 AgentLoop")

                else:

                    # 构建工具参数

                    tool_args = self._build_tool_args(tool_name, message, route_context)

                    print(f"[StreamHandler] 调用工具 {tool_name}，参数: {tool_args}")

                    

                    # 调用工具（在线程池中执行同步函数）

                    answer = await asyncio.to_thread(tool.invoke, tool_args)

                    

                    print(f"[StreamHandler] 工具 {tool_name} 返回: {str(answer)}")

                    

                    # 检查是否返回确认框

                    if isinstance(answer, dict) and answer.get("type") == "confirm":

                        yield self._format_sse("confirm", answer, "确认操作")

                        return

                    

                    # 检查是否返回错误

                    if isinstance(answer, dict) and answer.get("type") == "error":

                        yield self._format_sse("error", answer.get("message", "操作失败"), "错误")

                        yield self._format_sse("done", "", "完成", done=True)

                        return

                    

                    # 正常结果

                    self._ai_response_parts.append(str(answer))

                    self._ai_response_data_type = "text"

                    

                    if trace:

                        create_span(trace, "tool_direct_result", {

                            "tool_name": tool_name,

                            "result_length": len(str(answer)),

                        })

                    return

            except Exception as e:

                print(f"[StreamHandler] 直接调用工具 {tool_name} 失败: {str(e)}，fallback 到 AgentLoop")

        

        # Fallback：使用 AgentLoop

        try:

            from app.tools.agent_loop import run_agent

            

            combined_context = route_info

            if history_context:

                combined_context = f"{route_info}\n\n{history_context}" if route_info else history_context

            

            result = await run_agent(

                question=message,

                user_context=self.user_context,

                max_iterations=3,

                history_context=combined_context,

            )

            

            if trace:

                create_span(trace, "tool_result", {

                    "iterations": result.get("iterations", 0),

                    "tool_calls_count": result.get("tool_calls_count", 0),

                    "answer_length": len(result.get("answer", "")),

                })

            

            answer = result.get("answer", "")

            if isinstance(answer, dict) and answer.get("type") == "confirm":

                yield self._format_sse("confirm", answer, "确认操作")

            else:

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

            

            yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

    

    def _build_tool_args(self, tool_name: str, message: str, route_context: dict = None) -> dict:
        """
        根据工具名称和用户消息构建工具参数

        Args:
            tool_name: 工具名称
            message: 用户消息
            route_context: 路由上下文（包含 understanding, plan 等）

        Returns:
            工具参数字典
        """
        shop_id = self.user_context.shop_id

        # 查询类工具：只需要 shop_id 和可选参数
        query_tools = {
            "query_revenue": {"shop_id": shop_id},
            "query_packages": {"shop_id": shop_id},
            "query_top_packages": {"shop_id": shop_id},
            "query_customer": {"shop_id": shop_id, "keyword": self._extract_keyword(message)},
            "query_purchases": {"shop_id": shop_id},
            "query_game_sessions": {"shop_id": shop_id},
            "query_refunds": {"shop_id": shop_id},
            "query_inventory": {"shop_id": shop_id},
            "query_low_stock": {"shop_id": shop_id},
            "query_staff_list": {"shop_id": shop_id},
            "query_staff_performance": {"shop_id": shop_id},
            "query_coupons": {"shop_id": shop_id},
            "query_coupon_usages": {"shop_id": shop_id},
            "query_feedbacks": {"shop_id": shop_id},
            "query_staff_schedules": {"shop_id": shop_id},
            "query_attendance_records": {"shop_id": shop_id},
            "query_notifications": {"shop_id": shop_id},
            "query_daily_snapshots": {"shop_id": shop_id},
            "query_revenue_trend": {"shop_id": shop_id},
            "query_operation_logs": {"shop_id": shop_id},
        }

        if tool_name in query_tools:
            return query_tools[tool_name]

        # 操作类工具：从上下文提取参数
        args = {"shop_id": shop_id}
        understanding = (route_context or {}).get("understanding", "")
        history = self._get_history_text()

        # 退款相关：提取 refund_id
        if tool_name in ("refund_approve", "refund_reject"):
            import re
            combined = f"{understanding} {history}"
            # 匹配多种格式：退款单号：6、记录ID: 6、ID为6、单号6
            id_match = re.search(r'(?:退款单号|记录[Ii][Dd]|单号|ID)[为：:\s]*(\d+)', combined)
            if id_match:
                args["refund_id"] = int(id_match.group(1))
            # 提取顾客名（贪婪匹配中文+字母，排除标点）
            customer_match = re.search(r'(?:顾客|用户)[为：:]*["\u201c]?([\u4e00-\u9fa5a-zA-Z0-9_]+)["\u201d]?', combined)
            if customer_match:
                args["_customer_name"] = customer_match.group(1)

        # 退款拒绝：提取原因
        if tool_name == "refund_reject":
            reason_keywords = ["因为", "原因", "由于", "理由"]
            reason = ""
            for kw in reason_keywords:
                if kw in message:
                    reason = message.split(kw, 1)[1].strip()
                    break
            if not reason:
                for kw in reason_keywords:
                    if kw in understanding:
                        reason = understanding.split(kw, 1)[1].strip()
                        break
            if not reason:
                # 用用户原始消息作为原因（截取关键部分）
                reason = message.strip() if len(message.strip()) < 50 else "店长审批拒绝"
            args["reason"] = reason

        return args

    def _get_history_text(self) -> str:
        """获取最近的历史对话文本"""
        try:
            if self.session_id:
                from app.rag.session import get_session_manager
                session_mgr = get_session_manager()
                history = session_mgr.get_history(self.session_id)
                if history:
                    recent = history[-6:]  # 最近 3 轮
                    parts = []
                    for msg in recent:
                        role = msg.get("role", "")
                        content = msg.get("content", "")
                        if content:
                            parts.append(f"{role}: {content[:200]}")
                    return "\n".join(parts)
        except Exception:
            pass
        return ""

    

    def _extract_keyword(self, message: str) -> str:

        """从用户消息中提取搜索关键词（如顾客名）"""

        import re

        # 移除常见动词和助词

        stop_words = ["查一下", "查询", "查看", "查", "的", "信息", "详情", "帮我", "看看", "找一下"]

        keyword = message.strip()

        for word in stop_words:

            keyword = keyword.replace(word, "")

        keyword = keyword.strip()

        return keyword if keyword else ""

    

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

            

            yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

    

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

                

                yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

            

        except Exception as e:

            print(f"[StreamHandler] Vision 异常: {str(e)}")  # 只在控制台记录

            

            friendly_msg = "抱歉，图像识别出现问题，请稍后重试。"

            self._ai_response_parts.append(friendly_msg)

            self._ai_response_data_type = "text"

            

            yield self._format_sse("error", friendly_msg, "错误")

            yield self._format_sse("done", "", "完成", done=True)

    

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

