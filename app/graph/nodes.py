"""
Agent节点定义
实现Agent状态图中的各个节点
"""

from langchain_core.messages import AIMessage
from app.llm import get_chat_llm
from app.common.system_prompts import ROLE_DEFINITION
from app.graph.state import AgentState


def get_llm():
    """获取LLM实例"""
    return get_chat_llm()


async def route_node(state: AgentState) -> dict:
    """
    路由节点
    分析用户意图，决定下一步操作
    """
    last_message = state["messages"][-1].content

    # 简单的意图路由逻辑（后续可升级为LLM路由）
    intent_keywords = {
        "query": ["查询", "查看", "多少", "几个", "统计", "分析"],
        "tool": ["帮我", "请", "操作", "执行"],
        "knowledge": ["什么是", "怎么", "如何", "介绍", "说明"],
    }

    for intent, keywords in intent_keywords.items():
        if any(kw in last_message for kw in keywords):
            return {"next_step": intent}

    return {"next_step": "chat"}


async def rag_node(state: AgentState) -> dict:
    """
    RAG检索节点
    从知识库检索相关信息
    """
    from app.rag.chain import query_with_sources

    try:
        last_message = state["messages"][-1].content
        # 直接调用异步函数
        result = await query_with_sources(last_message)
        return {
            "context": result["answer"],
            "next_step": "respond",
        }
    except Exception as e:
        return {"error_message": f"检索失败: {str(e)}", "next_step": "error"}


async def nl2sql_node(state: AgentState) -> dict:
    """
    NL2SQL查询节点
    将自然语言转换为SQL并执行
    """
    import asyncio
    from app.nl2sql.safety import validate_sql, sanitize_sql, add_limit, add_shop_filter
    from app.nl2sql.executor import execute_sql_with_retry, format_results_for_llm
    from app.nl2sql.schema import get_schema_info
    from app.nl2sql.fewshot import retrieve_similar_examples, format_few_shot_prompt

    try:
        llm = get_llm()
        last_message = state["messages"][-1].content

        # 生成SQL（简化版本，实际应调用完整的NL2SQL Chain）
        from langchain_core.messages import HumanMessage
        
        prompt = f"""根据以下数据库结构和用户问题生成SQL:

{get_schema_info()}

用户问题: {last_message}

【安全规则】
1. 只生成 SELECT 查询，禁止 INSERT/UPDATE/DELETE/DROP
2. 如果问题与数据查询无关，返回 "-- 无法生成SQL: 非查询类问题"
3. 不要编造数据库结构或字段名

只返回SQL:"""
        
        response = await llm.ainvoke([HumanMessage(content=prompt)])

        sql = sanitize_sql(response.content.strip())
        is_safe, message = validate_sql(sql)

        if not is_safe:
            return {"error_message": f"SQL校验失败: {message}", "next_step": "error"}

        sql = add_shop_filter(sql, state["shop_id"])
        sql = add_limit(sql)

        # 使用 asyncio.to_thread 包装同步调用
        results = await asyncio.to_thread(execute_sql_with_retry, sql)
        formatted = format_results_for_llm(results)

        return {
            "tool_results": formatted,
            "next_step": "respond",
        }
    except Exception as e:
        return {"error_message": f"查询失败: {str(e)}", "next_step": "error"}


async def tool_node(state: AgentState) -> dict:
    """
    工具调用节点（LLM驱动 + 权限过滤）
    使用LLM分析用户问题，自动选择合适的工具并执行
    支持多工具并行调用，并根据用户角色过滤工具
    """
    from app.tools import TOOLS, TOOL_MAP
    from app.tools.permissions import get_tools_for_role
    from langchain_core.messages import SystemMessage, HumanMessage

    try:
        llm = get_chat_llm(temperature=0)
        last_message = state["messages"][-1].content
        shop_id = state["shop_id"]
        user_role = state.get("user_role", "guest")

        # 根据用户角色过滤可用工具
        available_tools = get_tools_for_role(user_role)
        available_tool_names = {t.name for t in available_tools}

        # 构建工具描述（只包含角色可用的工具）
        tools_desc = "\n".join([
            f"- {t.name}: {t.description}"
            for t in available_tools
        ])

        # 使用LLM选择工具
        system_prompt = f"""{ROLE_DEFINITION}

## 可用工具
{tools_desc}

## 要求
1. 分析用户问题，选择最合适的工具
2. 如果需要多个维度的数据，可以选择多个工具
3. 所有工具调用都需要 shop_id 参数
4. 返回JSON格式的工具调用列表
5. 【禁止编造】如果没有合适的工具，返回空数组 []，不要编造不存在的工具

## 输出格式
```json
[
  {{"tool": "工具名", "args": {{"shop_id": {shop_id}, "其他参数": "值"}}}}
]
```
只返回JSON，不要其他解释。"""

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=last_message)
        ])

        # 解析LLM返回的工具调用
        import json
        import re

        json_match = re.search(r'\[[^\]]*\]', response.content, re.DOTALL)
        if not json_match:
            return {
                "tool_results": "无法确定需要调用的工具",
                "next_step": "respond",
            }

        tool_calls = json.loads(json_match.group())

        # 执行工具调用（带权限校验）
        results = []
        for call in tool_calls:
            tool_name = call.get("tool")
            args = call.get("args", {})

            # 确保shop_id存在
            if "shop_id" not in args:
                args["shop_id"] = shop_id

            # 权限校验
            if tool_name not in available_tool_names:
                results.append(f"【{tool_name}】无权限访问")
                continue

            tool = TOOL_MAP.get(tool_name)
            if tool:
                try:
                    result = await tool.ainvoke(args)
                    results.append(f"【{tool_name}】\n{result}")
                except Exception as e:
                    results.append(f"【{tool_name}】调用失败: {str(e)}")
            else:
                results.append(f"【{tool_name}】工具不存在")

        return {
            "tool_results": "\n\n".join(results) if results else "未找到合适的工具",
            "next_step": "respond",
        }
    except Exception as e:
        return {"error_message": f"工具调用失败: {str(e)}", "next_step": "error"}


async def respond_node(state: AgentState) -> dict:
    """
    响应生成节点
    根据检索结果或工具结果生成最终回答
    """
    from langchain_core.messages import HumanMessage
    
    llm = get_llm()

    context = state.get("context", "")
    tool_results = state.get("tool_results", "")
    error_message = state.get("error_message", "")

    if error_message:
        return {"messages": [AIMessage(content=f"抱歉，处理过程中出现错误: {error_message}")]}]

    information = context or tool_results
    last_message = state["messages"][-1].content

    prompt = f"""{ROLE_DEFINITION}

请根据以下信息回答用户问题。

相关信息：
{information}

用户问题：{last_message}

请用友好、专业的语气回答："""

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return {"messages": [AIMessage(content=response.content)]}


async def error_node(state: AgentState) -> dict:
    """错误处理节点"""
    error_message = state.get("error_message", "未知错误")
    return {"messages": [AIMessage(content=f"抱歉，处理过程中出现错误: {error_message}")]}
