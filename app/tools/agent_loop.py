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
from app.common.system_prompts import ROLE_DEFINITION, SECURITY_RULES

logger = logging.getLogger(__name__)


# ==================== 通用 SQL 执行工具 ====================

from langchain_core.tools import tool

@tool
def execute_sql_query(sql: str, params: str = "{}") -> str:
    """
    执行 SQL 查询并返回结果。
    
    用途：
    - 查询任意表的数据（如字典表、业务表）
    - 查询字典表获取状态映射（如 status=1 是什么意思）
    - 统计分析
    
    参数：
    - sql: SELECT 查询语句
    - params: JSON 格式的参数（可选，如 {"shop_id": 5}）
    
    注意：
    - 只允许 SELECT 语句
    - 结果限制 100 行
    - 可以查询 sys_dicts 表获取状态映射
    """
    import json as _json
    from app.nl2sql.executor import execute_sql
    
    # 安全校验
    if not sql.strip().upper().startswith("SELECT"):
        return "错误：只允许 SELECT 查询"
    
    # 解析参数
    try:
        params_dict = _json.loads(params) if params and params.strip() else {}
    except _json.JSONDecodeError:
        params_dict = {}
    
    # 执行查询
    try:
        results = execute_sql(sql, params_dict)
        if not results:
            return "查询结果为空"
        
        # 格式化结果
        if isinstance(results, list) and len(results) > 0:
            # 提取列名
            columns = list(results[0].keys())
            lines = [" | ".join(columns)]
            lines.append(" | ".join(["---"] * len(columns)))
            for row in results[:100]:  # 限制 100 行
                lines.append(" | ".join([str(row.get(col, "")) for col in columns]))
            return "\n".join(lines)
        else:
            return str(results)
    except Exception as e:
        return f"查询失败: {str(e)}"


@tool
def list_tables(keyword: str = "") -> str:
    """
    列出数据库表，帮助理解数据结构。
    
    用途：
    - 不确定数据存在哪个表时使用
    - 需要了解系统有哪些数据时使用
    
    参数：
    - keyword: 可选，按关键字过滤表名（如"refund"、"customer"）
    """
    from app.nl2sql.schema import get_schema_info
    
    try:
        schema = get_schema_info()
        tables = []
        for table_name, table_info in schema.items():
            if keyword and keyword.lower() not in table_name.lower():
                continue
            desc = table_info.get("comment", "") or table_name
            tables.append(f"- {table_name}: {desc}")
        
        if not tables:
            return f"没有找到包含 '{keyword}' 的表"
        
        return "数据库表列表：\n" + "\n".join(tables[:50])
    except Exception as e:
        return f"获取表列表失败: {str(e)}"


@tool
def describe_table(table_name: str) -> str:
    """
    描述表结构，包括字段名、类型、说明。
    
    用途：
    - 不确定某个字段的含义时使用
    - 需要了解表有哪些字段时使用
    
    参数：
    - table_name: 表名（如"refund_records"、"customers"）
    """
    from app.nl2sql.schema import get_schema_info
    
    try:
        schema = get_schema_info()
        table_info = schema.get(table_name)
        
        if not table_info:
            return f"表 '{table_name}' 不存在"
        
        columns = table_info.get("columns", [])
        if not columns:
            return f"表 '{table_name}' 没有列信息"
        
        lines = [f"表 {table_name} 的结构："]
        for col in columns:
            name = col.get("name", "")
            col_type = col.get("type", "")
            comment = col.get("comment", "") or ""
            lines.append(f"- {name} ({col_type}): {comment}")
        
        return "\n".join(lines)
    except Exception as e:
        return f"获取表结构失败: {str(e)}"


@tool
def search_docs(query: str) -> str:
    """
    搜索知识库文档，查找相关信息。
    
    用途：
    - 需要查找业务规则、政策、流程时使用
    - 不确定某个概念的定义时使用
    
    参数：
    - query: 搜索关键词（如"退款政策"、"营业时间"）
    """
    try:
        from app.rag.agentic_rag import AgenticRAG
        from app.common.user_context import UserContext
        
        rag = AgenticRAG()
        # 使用空的 UserContext 进行搜索
        ctx = UserContext(shop_id=0, user_id=0, role="guest")
        result = rag.execute(query, ctx)
        
        if result and result.get("success"):
            return result.get("result", "未找到相关信息")
        else:
            return "未找到相关信息"
    except Exception as e:
        return f"搜索失败: {str(e)}"


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
            "success": bool(self.answer and self.answer.strip() and "无法生成回答" not in self.answer),
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
        
        # 确保 execute_sql_query 工具在列表中
        if execute_sql_query not in self.tools:
            self.tools = list(self.tools) + [execute_sql_query]
        
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
        backend_nav = self._get_backend_navigation()
        return f"""{ROLE_DEFINITION}{SECURITY_RULES}

## 可用工具
{tools_desc}

## 执行规则（必须遵守）

### 优先级 1：直接执行
如果有对应的工具，直接执行：
- 查询类 → 使用 execute_sql_query 或其他查询工具
- 操作类 → 调用对应的操作工具（refund_approve、grant_coupon 等）
- 知识类 → 基于已有知识回答

### 优先级 2：引导后台
如果没有对应的工具，引导用户到后台系统操作：
- 说明原因：「智能助手暂不支持XX操作」
- 给出路径：「您可以到【XX页面】（路径：/xx/xx）操作」
- 说明功能：「在该页面可以XX、XX、XX」

### 判断方法
1. 用户请求 → 检查工具列表 → 有则执行，无则引导
2. 不要猜测，不要编造能力
3. 不要说"您可以到后台操作"然后又说"我来帮您查询"——要么执行，要么引导

## 后台系统导航
{backend_nav}

## 数据调查能力（重要）
当你遇到不确定的信息时，不要猜测，主动探索：

### 探索工具
- **execute_sql_query**: 执行 SQL 查询，获取数据
- **list_tables**: 列出数据库表，了解系统有哪些数据
- **describe_table**: 查看表结构，了解字段含义
- **search_docs**: 搜索知识库，查找业务规则

### 探索策略
1. 遇到状态码（如 status=1）→ 查询 sys_dicts 表获取映射
2. 不确定表结构 → 使用 describe_table 查看
3. 不确定数据在哪个表 → 使用 list_tables 查找
4. 需要业务规则 → 使用 search_docs 搜索知识库

### 探索原则
- 不要猜测，要查询验证
- 可以多次调用工具来获取完整信息
- 不要在第一次查询失败时就放弃，尝试不同的查询方式
- 如果找不到答案，诚实告知用户

## 输出规范（必须遵守）
1. **所有输出必须是人类可读的**，不能使用原始代码或数字指代
2. 状态字段必须映射为中文标签：
   - 退款状态：1=处理中, 2=已完成, 3=已拒绝
   - 套餐类型：1=单次, 2=周卡, 3=月卡
   - 优惠券类型：1=固定金额, 2=百分比, 3=兑换券
3. 如果数据中包含原始状态码，必须在回答中转换为中文
4. 列名使用中文：status→状态, amount→金额, nickname→顾客姓名

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
    
    def _get_backend_navigation(self) -> str:
        """生成后台系统导航信息"""
        import json
        import os
        
        try:
            cap_file = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'system_capabilities.json')
            with open(cap_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            pages = data.get('pages', [])
            lines = []
            for page in pages:
                features = ", ".join([f["name"] for f in page.get("features", [])])
                lines.append(f"- **{page['name']}**（{page['path']}）: {page['description']} | 功能: {features}")
            
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"加载系统能力文档失败: {e}")
            return "（系统能力文档加载失败）"
    
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
                logger.error(f"[LangFuse] 记录 Span 失败: {str(e)}")
        
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
