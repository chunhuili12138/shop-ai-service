"""
LLM Agent - 总结分析建议 Agent
专门用于总结、分析、建议等任务
不检索知识库，不搜索互联网，只使用 LLM 通用知识和上下文
"""

from typing import Optional
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm import get_chat_llm
from app.common.user_context import UserContext
from app.multi_agent.protocol import AgentResult, AgentType


# 系统提示词（只负责任务执行，角色/安全/合规由最终汇总步骤统一处理）
LLM_SYSTEM_PROMPT = """你是一个数据检索助手。根据用户问题和上下文，返回相关的分析内容。

你的职责：
1. 基于提供的数据进行分析和总结
2. 给出专业、可操作的经营建议
3. 返回的内容将由另一个系统进行汇总和格式化

重要规则：
1. 只使用提供的数据进行分析，不要编造数据
2. 如果数据不足，诚实说明并给出通用建议
3. 不要添加角色扮演内容

【绝对禁止编造数据】
- 如果没有提供具体数据（如营业额、顾客名、订单号等），你必须说"未查到相关数据"或"暂无数据"
- 绝对不允许自己创造、编造、虚构任何具体数据
- 你只能基于上下文中实际提供的数据进行分析
- 如果你没有真实数据，直接说没有，不要编造看起来合理的数字或名称"""


class LLMAgent:
    """
    LLM Agent - 总结分析建议
    
    功能：
    - 基于数据进行分析总结
    - 给出经营建议
    - 不检索知识库，不搜索互联网
    """
    
    async def execute(self, task: str, context: UserContext, **kwargs) -> AgentResult:
        """
        执行 LLM 总结分析任务
        
        Args:
            task: 用户任务
            context: 用户上下文
            **kwargs: 额外参数
                - route_info: 路由分析结果
                - history_context: 历史上下文
        
        Returns:
            执行结果
        """
        try:
            from datetime import datetime
            
            llm = get_chat_llm()
            
            # 获取额外参数
            route_info = kwargs.get("route_info", "")
            history_context = kwargs.get("history_context", "")
            
            # 构建包含上下文的提示词
            current_date = datetime.now().strftime("%Y年%m月%d日")
            
            system_prompt = f"""{LLM_SYSTEM_PROMPT}

当前日期：{current_date}
店铺名称：{context.shop_name or '未知'}
用户角色：{context.role}"""
            
            # 构建用户消息（包含上下文）
            user_message = task
            if route_info:
                user_message = f"""【Router 分析结果】
{route_info}

【用户问题】
{task}"""
            
            if history_context:
                user_message = f"""【历史对话】
{history_context}

{user_message}"""
            
            # 调用 LLM
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            
            response = await llm.ainvoke(messages)
            
            return AgentResult(
                agent=AgentType.LLM,
                result=response.content,
                confidence=0.9,
                metadata={
                    "current_date": current_date,
                    "shop_name": context.shop_name,
                }
            )
        except Exception as e:
            print(f"[LLMAgent] 执行失败: {str(e)}")
            return AgentResult(
                agent=AgentType.LLM,
                result=f"分析失败: {str(e)}",
                confidence=0.0,
                success=False,
                error=str(e)
            )


# 全局实例
_llm_agent = None


def get_llm_agent() -> LLMAgent:
    """获取 LLM Agent 单例"""
    global _llm_agent
    if _llm_agent is None:
        _llm_agent = LLMAgent()
    return _llm_agent
