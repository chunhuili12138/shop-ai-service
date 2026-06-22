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

【可用操作工具（重要）】
系统支持以下操作，不要说"系统不支持"：
- material_inbound: 物料入库（已有物料）
- material_outbound: 物料出库
- refund_approve: 批准退款
- refund_reject: 拒绝退款
- grant_coupon: 发放优惠券
- game_session_checkin: 核销入座
- game_session_finish: 结束游玩
- reply_feedback: 回复评价
- send_notification: 发送通知

如果用户需要执行这些操作，应该引导他们使用对应的工具，而不是说"系统不支持"。

【后台系统导航】
当智能助手无法直接解决问题时，引导用户到后台系统操作：
- 物料管理: /inventory/material（添加物料、编辑物料）
- 库存查询: /inventory/stock（查看库存、入库、出库）
- 退款管理: /trade/refund（批准/拒绝退款）
- 顾客管理: /customer（查看顾客信息）
- 套餐管理: /package（管理套餐）
- 优惠券管理: /marketing/coupon（管理优惠券）
- 员工管理: /system/staff（管理员工）
- 评价管理: /feedback（查看/回复评价）

【任务执行结果使用规则（重要）】
1. 如果用户消息中有"任务执行结果"部分，这就是你要用的数据
2. 不要重新查询，直接基于这些数据生成回答
3. 如果数据中有"0"值（如核销0次），这是有效数据，不是"没有数据"
4. 基于数据生成总结分析，不要说"未查到数据"

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
                - task_results: 任务执行结果列表
                    [{"id": 1, "status": "success", "result": "..."}, ...]
        
        Returns:
            执行结果
        """
        try:
            from datetime import datetime
            
            llm = get_chat_llm()
            
            # 获取额外参数
            route_info = kwargs.get("route_info", "")
            history_context = kwargs.get("history_context", "")
            task_results = kwargs.get("task_results", [])
            
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
            
            # 添加任务执行结果（独立的部分，不混入任务描述）
            if task_results:
                results_text = "\n\n## 任务执行结果（必须基于这些数据回答）\n"
                for tr in task_results:
                    status_icon = "✓" if tr.get("status") == "success" else "✗"
                    task_desc = tr.get("task", f"子任务{tr.get('id', '?')}")
                    result_text = tr.get("result", "无结果")
                    results_text += f"{status_icon} {task_desc}: {result_text}\n"
                user_message += results_text
            
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
