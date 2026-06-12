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


# 系统提示词
LLM_SYSTEM_PROMPT = """你是一个专业的店铺智能助手，负责帮助店主分析经营数据、提供运营建议。

你的职责：
1. 基于提供的数据进行分析和总结
2. 给出专业、可操作的经营建议
3. 用友好、专业的语气回答

重要规则：
1. 只使用提供的数据进行分析，不要编造数据
2. 如果数据不足，诚实说明并给出通用建议
3. 不要提及你是AI模型，直接给出分析结果
4. 支持 Markdown 格式输出"""


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
            task: 用户任务（可能包含数据上下文）
            context: 用户上下文
        
        Returns:
            执行结果
        """
        try:
            from datetime import datetime
            
            llm = get_chat_llm()
            
            # 构建包含上下文的提示词
            current_date = datetime.now().strftime("%Y年%m月%d日")
            
            system_prompt = f"""{LLM_SYSTEM_PROMPT}

当前日期：{current_date}
店铺名称：{context.shop_name or '未知'}
用户角色：{context.role}"""
            
            # 调用 LLM
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=task),
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
