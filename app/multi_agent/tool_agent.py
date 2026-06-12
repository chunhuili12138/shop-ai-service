"""
Tool Agent - 工具调用 Agent
调用现有工具模块执行查询
集成经验池学习
"""

from typing import Optional
from app.common.user_context import UserContext
from app.multi_agent.protocol import AgentResult, AgentType
from app.tools import TOOLS, TOOL_MAP
from app.tools.permissions import get_tools_for_role
from app.experience.pool import get_experience_pool


class ToolAgent:
    """
    Tool Agent - 工具调用
    
    功能：
    - 调用现有工具执行查询
    - 支持角色权限过滤
    - 集成经验池学习
    """
    
    async def execute(self, task: str, context: UserContext, **kwargs) -> AgentResult:
        """
        执行工具调用任务
        
        Args:
            task: 用户任务
            context: 用户上下文
        
        Returns:
            执行结果
        """
        experience_pool = get_experience_pool()
        
        try:
            # 1. 检索经验池
            similar_exps = await experience_pool.retrieve_similar("tool", task, k=2)
            experience_prompt = experience_pool.format_for_prompt(similar_exps)
            
            # 2. 调用现有 Agent Loop
            from app.tools.agent_loop import run_agent
            
            result = await run_agent(
                question=task,
                user_context=context,
                max_iterations=3,
                include_messages=False,
                experience_context=experience_prompt,  # 传递经验上下文
            )
            
            answer = result.get("answer", "")
            
            # 3. 成功时记录到经验池
            if result.get("success", False):
                await experience_pool.record_success(
                    agent_type="tool",
                    question=task,
                    solution=str(answer),
                    result_summary=str(answer)[:200],
                )
            
            return AgentResult(
                agent=AgentType.TOOL,
                result=answer,
                confidence=0.9,
                metadata={
                    "iterations": result.get("iterations", 0),
                    "tool_calls_count": result.get("tool_calls_count", 0),
                    "model_used": result.get("model_used", ""),
                }
            )
        except Exception as e:
            print(f"[ToolAgent] 执行失败: {str(e)}")
            
            # 记录失败案例
            await experience_pool.record_failure_and_fix(
                agent_type="tool",
                question=task,
                error=str(e),
                original_solution="",
            )
            
            return AgentResult(
                agent=AgentType.TOOL,
                result=f"工具调用失败: {str(e)}",
                confidence=0.0,
                success=False,
                error=str(e)
            )
