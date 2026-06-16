"""
Agent 循环执行器
实现 Agent 循环 + 并行执行的混合模式

核心机制：
1. LLM 动态决策需要调用哪些工具
2. 如果本轮有多个 tool_calls，自动并行执行
3. 汇总 Observation，继续下一轮决策
4. 直到 LLM 决定不再调用工具，生成最终答案

Day 5-6 新增：
- 权限隔离：根据用户上下文过滤工具
- 动态 Prompt：根据角色生成系统提示词
- 动态模型：根据问题复杂度选择模型
"""

import asyncio
import time
import logging
from typing import Annotated, Any, Dict, List, Optional, Sequence, TypedDict
from dataclasses import dataclass, field
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
)
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages
from app.llm import get_chat_llm, get_chat_llm_by_model, select_model
from app.config import settings
from app.tools import TOOLS
from app.common.user_context import UserContext
from app.tools.permissions import get_tools_for_role
from app.tools.prompt_templates import get_system_prompt

logger = logging.getLogger(__name__)


# ==================== 状态定义 ====================

class AgentLoopState(TypedDict):
    """Agent 循环状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    shop_id: int
    user_id: int
    role: str
    iteration: int
    max_iterations: int
    start_time: float


# ==================== 结果定义 ====================

@dataclass
class AgentLoopResult:
    """Agent 循环执行结果"""
    answer: str
    iterations: int
    tool_calls_count: int
    total_duration_ms: float
    model_used: str  # 使用的模型
    role: str  # 用户角色
    messages: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "answer": self.answer,
            "iterations": self.iterations,
            "tool_calls_count": self.tool_calls_count,
            "total_duration_ms": self.total_duration_ms,
            "model_used": self.model_used,
            "role": self.role,
            "messages": [
                {
                    "role": self._get_message_role(msg),
                    "content": self._get_message_content(msg),
                    "tool_calls": self._get_tool_calls(msg),
                }
                for msg in self.messages
            ]
        }
    
    def _get_message_role(self, msg) -> str:
        if isinstance(msg, HumanMessage):
            return "user"
        elif isinstance(msg, AIMessage):
            return "assistant"
        elif isinstance(msg, SystemMessage):
            return "system"
        elif isinstance(msg, ToolMessage):
            return "tool"
        return "unknown"
    
    def _get_message_content(self, msg) -> str:
        if hasattr(msg, 'content'):
            return str(msg.content)
        return ""
    
    def _get_tool_calls(self, msg) -> List[Dict]:
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls'):
            return [
                {
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                }
                for tc in msg.tool_calls
            ]
        return []


# ==================== Agent 循环执行器 ====================

class AgentLoop:
    """
    Agent 循环执行器
    
    实现混合模式：
    - LLM 动态决策需要调用哪些工具
    - 如果本轮有多个 tool_calls，自动并行执行
    - 汇总 Observation，继续下一轮决策
    
    Day 5-6 新增：
    - 权限隔离：根据用户上下文过滤工具
    - 动态 Prompt：根据角色生成系统提示词
    - 动态模型：根据问题复杂度选择模型
    """
    
    def __init__(
        self,
        tools: List[BaseTool] = None,
        max_iterations: int = 5,
        user_context: UserContext = None,
    ):
        """
        初始化 Agent 循环
        
        Args:
            tools: 工具列表（默认根据角色过滤）
            max_iterations: 最大迭代次数
            user_context: 用户上下文
        """
        self.user_context = user_context
        self.max_iterations = max_iterations
        
        # 根据用户上下文过滤工具
        if tools is not None:
            self.tools = tools
        elif user_context:
            self.tools = get_tools_for_role(user_context.role)
        else:
            self.tools = TOOLS
        
        # 生成系统提示词
        if user_context:
            self.system_prompt = get_system_prompt(user_context)
        else:
            self.system_prompt = self._default_system_prompt()
        
        # 动态选择模型（初始使用 flash，后续根据复杂度调整）
        self.model_type = "flash"
        self.llm = get_chat_llm_by_model(self.model_type).bind_tools(self.tools)
        
        # 创建工具节点（自动并行执行，带超时保护）
        self.tool_node = ToolNode(self.tools)
        # 包装工具节点，添加超时控制
        self._original_tool_node = self.tool_node
        self.tool_node = self._wrap_tool_with_timeout(self.tool_node)
        
        # 构建状态图
        self.graph = self._build_graph()

    def _wrap_tool_with_timeout(self, tool_node: ToolNode):
        """
        包装 ToolNode，为每个工具调用添加超时保护

        Args:
            tool_node: 原始 ToolNode 实例

        Returns:
            包装后的异步函数
        """
        timeout_seconds = settings.AGENT_TIMEOUT

        async def tool_node_with_timeout(state):
            try:
                return await asyncio.wait_for(
                    tool_node.ainvoke(state),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.warning(f"工具执行超时 ({timeout_seconds}s)")
                # 返回超时错误消息，终止 Agent 循环
                from langchain_core.messages import AIMessage
                return {
                    "messages": [AIMessage(content=f"工具执行超时（{timeout_seconds}秒），请尝试简化问题或稍后重试。")]
                }

        return tool_node_with_timeout

    def _default_system_prompt(self) -> str:
        """默认系统提示词"""
        tools_desc = self._get_tools_description()
        return f"""你是店铺智能助手，负责帮助店长查询和分析店铺数据。

## 可用工具
{tools_desc}

## 工作原则
1. 根据用户问题，选择合适的工具查询数据
2. 如果需要多个维度的数据，可以同时调用多个工具
3. 基于工具返回的结果，生成清晰、友好的回答
4. 如果工具调用失败，诚实告知用户"查询失败"或"未查到数据"
5. 所有数据查询都需要指定 shop_id

## 回答要求
- 使用中文回答
- 数据要准确，不要编造
- 回答要简洁明了
- 如果是统计数据，说明具体数值

【绝对禁止编造数据】
- 如果工具返回空结果或查询失败，必须如实告知"未查到数据"
- 绝对不允许自己编造、虚构任何数据（顾客名、订单号、金额等）
- 没有真实数据就直接说没有，不要编造看起来合理的数字"""
    
    def _get_tools_description(self) -> str:
        """获取工具描述"""
        descriptions = []
        for tool in self.tools:
            desc = f"- **{tool.name}**: {tool.description}"
            if hasattr(tool, 'args_schema') and tool.args_schema:
                try:
                    schema = tool.args_schema.schema()
                    if 'properties' in schema:
                        params = list(schema['properties'].keys())
                        desc += f"\n  参数: {', '.join(params)}"
                except Exception:
                    pass
            descriptions.append(desc)
        return "\n".join(descriptions)
    
    def _build_graph(self) -> StateGraph:
        """
        构建 Agent 状态图
        
        图结构：
        start -> agent -> [tools -> agent]* -> end
        """
        workflow = StateGraph(AgentLoopState)
        
        # 添加节点
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", self.tool_node)
        
        # 设置入口
        workflow.set_entry_point("agent")
        
        # 条件边：判断是否继续调用工具
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "end": END,
            }
        )
        
        # 工具执行后回到 Agent 决策
        workflow.add_edge("tools", "agent")
        
        return workflow.compile()
    
    def _agent_node(self, state: AgentLoopState) -> Dict:
        """
        Agent 决策节点
        LLM 分析当前状态，决定调用哪些工具或生成最终答案
        """
        messages = list(state["messages"])
        
        # 添加系统提示词（如果是第一条消息）
        if not any(isinstance(m, SystemMessage) for m in messages):
            system_msg = SystemMessage(content=self.system_prompt)
            messages = [system_msg] + messages
        
        # 调用 LLM（设置超时）
        try:
            response = self.llm.invoke(messages)
        except Exception as e:
            logger.error(f"LLM 调用失败: {str(e)}")
            # 返回错误消息，结束循环
            error_msg = AIMessage(content=f"抱歉，AI 服务暂时不可用，请稍后再试。错误信息：{str(e)}")
            return {
                "messages": [error_msg],
                "iteration": state["iteration"] + 1,
            }
        
        return {
            "messages": [response],
            "iteration": state["iteration"] + 1,
        }
    
    def _should_continue(self, state: AgentLoopState) -> str:
        """
        判断是否继续执行工具
        
        Returns:
            "continue": 继续执行工具
            "end": 结束循环
        """
        # 检查迭代次数
        if state["iteration"] >= state["max_iterations"]:
            return "end"
        
        # 检查最后一条消息是否有工具调用
        last_message = state["messages"][-1]
        
        if isinstance(last_message, AIMessage):
            if last_message.tool_calls and len(last_message.tool_calls) > 0:
                return "continue"
        
        return "end"
    
    async def run(
        self,
        question: str,
        user_context: UserContext = None,
        include_messages: bool = False,
        history_context: str = "",
    ) -> AgentLoopResult:
        """
        执行 Agent 循环
        
        Args:
            question: 用户问题
            user_context: 用户上下文（可选，覆盖初始化时的上下文）
            include_messages: 是否在结果中包含完整消息历史
            history_context: 历史上下文（纪要 + 最近对话）
        
        Returns:
            执行结果
        """
        from monitoring.langfuse_config import create_trace, create_span, flush
        
        start_time = time.time()
        
        # 使用传入的上下文或初始化时的上下文
        ctx = user_context or self.user_context
        shop_id = ctx.shop_id if ctx else 1
        user_id = ctx.user_id if ctx else 0
        role = ctx.role if ctx else "guest"
        
        # 创建 LangFuse Trace
        trace = create_trace(
            name="agent_loop",
            metadata={
                "shop_id": shop_id,
                "user_id": user_id,
                "role": role,
                "question": question[:200],  # 截断过长问题
            }
        )
        
        # 动态选择模型（简单规则：第一轮用 flash，后续用 pro）
        # 这里可以根据问题复杂度更精细地选择
        model_type = self._select_model_for_question(question)
        
        # 如果模型类型变化，重新创建 LLM
        if model_type != self.model_type:
            self.model_type = model_type
            self.llm = get_chat_llm_by_model(self.model_type).bind_tools(self.tools)
        
        # 初始状态
        # 如果有历史上下文，将其添加到问题前面
        full_question = question
        if history_context:
            full_question = f"""【对话历史】
{history_context}

【当前问题】
{question}"""
        
        initial_state = {
            "messages": [
                HumanMessage(content=f"[店铺ID: {shop_id}] {full_question}")
            ],
            "shop_id": shop_id,
            "user_id": user_id,
            "role": role,
            "iteration": 0,
            "max_iterations": self.max_iterations,
            "start_time": start_time,
        }
        
        # 执行状态图（带超时）
        try:
            coro = self.graph.ainvoke(initial_state)
            final_state = await asyncio.wait_for(coro, timeout=settings.AGENT_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(f"Agent 执行超时 ({settings.AGENT_TIMEOUT}s)")
            # 返回超时结果
            return AgentLoopResult(
                answer=f"抱歉，AI 处理超时（超过{settings.AGENT_TIMEOUT}秒），请稍后再试。",
                iterations=initial_state.get("iteration", 0),
                tool_calls_count=0,
                total_duration_ms=(time.time() - start_time) * 1000,
                model_used=self.model_type,
                role=role,
                messages=[],
            )
        
        # 计算执行时间
        total_duration_ms = (time.time() - start_time) * 1000
        
        # 提取最终答案
        messages = list(final_state["messages"])
        answer = self._extract_answer(messages)
        
        # 统计工具调用次数
        tool_calls_count = self._count_tool_calls(messages)
        
        # 记录 LangFuse Span（工具调用统计）
        if trace:
            try:
                create_span(
                    trace,
                    name="agent_result",
                    metadata={
                        "iterations": final_state["iteration"],
                        "tool_calls_count": tool_calls_count,
                        "total_duration_ms": total_duration_ms,
                        "model_used": self.model_type,
                        "answer_length": len(answer) if answer else 0,
                    }
                )
            except Exception as e:
                print(f"[LangFuse] 记录 Span 失败: {str(e)}")
        
        # 刷新 LangFuse 缓存
        flush()
        
        return AgentLoopResult(
            answer=answer,
            iterations=final_state["iteration"],
            tool_calls_count=tool_calls_count,
            total_duration_ms=total_duration_ms,
            model_used=self.model_type,
            role=role,
            messages=messages if include_messages else [],
        )
    
    def _select_model_for_question(self, question: str) -> str:
        """
        根据问题选择模型
        
        Args:
            question: 用户问题
        
        Returns:
            模型类型
        """
        # 简单规则：
        # - 包含"分析"、"对比"、"趋势"等复杂词汇用 pro
        # - 其他用 flash
        complex_keywords = ["分析", "对比", "趋势", "比较", "排名", "汇总", "总结", "报告"]
        
        for keyword in complex_keywords:
            if keyword in question:
                return "pro"
        
        return "flash"
    
    def _extract_answer(self, messages: List[BaseMessage]) -> str:
        """从消息历史中提取最终答案"""
        # 从后往前找最后一条 AIMessage
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                # 如果有工具调用但没有内容，继续找
                if msg.tool_calls and not msg.content:
                    continue
                return msg.content
        return "抱歉，无法生成回答。"
    
    def _count_tool_calls(self, messages: List[BaseMessage]) -> int:
        """统计工具调用次数"""
        count = 0
        for msg in messages:
            if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls'):
                count += len(msg.tool_calls)
        return count


# ==================== 全局实例 ====================

_agent_loop: Optional[AgentLoop] = None


def get_agent_loop(
    tools: List[BaseTool] = None,
    max_iterations: int = 5,
    user_context: UserContext = None,
) -> AgentLoop:
    """
    获取 Agent 循环实例
    
    Args:
        tools: 工具列表
        max_iterations: 最大迭代次数
        user_context: 用户上下文
    
    Returns:
        AgentLoop 实例
    """
    global _agent_loop
    if _agent_loop is None:
        _agent_loop = AgentLoop(
            tools=tools,
            max_iterations=max_iterations,
            user_context=user_context,
        )
    return _agent_loop


async def run_agent(
    question: str,
    user_context: UserContext,
    max_iterations: int = 5,
    include_messages: bool = False,
    history_context: str = "",
    experience_context: str = "",
) -> Dict:
    """
    执行 Agent 循环（API 接口）
    
    Args:
        question: 用户问题
        user_context: 用户上下文
        max_iterations: 最大迭代次数
        include_messages: 是否包含消息历史
        history_context: 历史上下文（纪要 + 最近对话）
        experience_context: 经验上下文（来自经验池）
    
    Returns:
        执行结果字典
    """
    # 合并历史上下文和经验上下文
    combined_context = ""
    if history_context:
        combined_context += history_context
    if experience_context:
        if combined_context:
            combined_context += "\n\n"
        combined_context += experience_context
    
    # 每次调用创建新的 AgentLoop 实例（确保使用最新的用户上下文）
    agent = AgentLoop(
        max_iterations=max_iterations,
        user_context=user_context,
    )
    result = await agent.run(question, user_context, include_messages, combined_context)
    return result.to_dict()


async def run_agent_simple(
    question: str,
    shop_id: int,
    role: str = "店长",
    max_iterations: int = 5,
) -> Dict:
    """
    简化版 Agent 循环（用于测试）
    
    Args:
        question: 用户问题
        shop_id: 店铺 ID
        role: 用户角色
        max_iterations: 最大迭代次数
    
    Returns:
        执行结果字典
    """
    user_context = UserContext(
        user_id=0,
        shop_id=shop_id,
        role=role,
    )
    return await run_agent(question, user_context, max_iterations)
