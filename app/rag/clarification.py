"""
Query Clarification模块
当用户问题模糊时，主动询问用户以澄清问题
"""

from typing import Optional
from langchain_core.messages import HumanMessage
from app.llm import get_chat_llm


# 追问生成Prompt
CLARIFICATION_PROMPT = """你是一个店铺智能助手。用户的问题不够明确，请生成追问提示。

用户问题：{question}

已检索到的信息：
{context}

请根据以上信息，生成一个友好的追问提示，帮助用户明确需求。

要求：
1. 列出3-5个可能的选项
2. 选项要具体、清晰
3. 语气友好、专业

请用以下JSON格式返回：
{{
    "message": "追问提示语",
    "options": ["选项1", "选项2", "选项3"]
}}

只返回JSON，不要其他内容。"""

# 最大追问轮数
MAX_CLARIFICATION_ROUNDS = 3

# 低置信度阈值
LOW_CONFIDENCE_THRESHOLD = 0.4


class QueryClarifier:
    """
    Query Clarification模块
    
    当用户问题模糊时，主动询问用户以澄清问题。
    
    触发条件：
    - 置信度 < 0.4
    - 未超过最大追问次数（3次）
    """

    def __init__(self):
        self.llm = None

    def _get_llm(self):
        """获取LLM实例"""
        if self.llm is None:
            self.llm = get_chat_llm(temperature=0.7)
        return self.llm

    def should_clarify(self, confidence: float, clarification_count: int) -> bool:
        """
        判断是否需要追问
        
        Args:
            confidence: 置信度（0-1）
            clarification_count: 当前已追问次数
        
        Returns:
            是否需要追问
        """
        should = confidence < LOW_CONFIDENCE_THRESHOLD and clarification_count < MAX_CLARIFICATION_ROUNDS
        if should:
            print(f"[追问判断] 置信度={confidence:.2f}, 已追问{clarification_count}次 → 需要追问")
        else:
            print(f"[追问判断] 置信度={confidence:.2f}, 已追问{clarification_count}次 → 不需要追问")
        return should

    def generate_clarification(
        self, 
        question: str, 
        sources: list[dict] = None
    ) -> dict:
        """
        生成追问提示
        
        Args:
            question: 用户问题
            sources: 检索到的来源
        
        Returns:
            {
                "message": str,  # 追问提示语
                "options": list[str],  # 选项列表
            }
        """
        try:
            llm = self._get_llm()
            
            # 格式化来源信息
            context = "暂无相关信息"
            if sources:
                context = "\n".join([
                    f"- {s.get('content', '')[:100]}" 
                    for s in sources[:3]
                ])
            
            # 生成追问
            prompt = CLARIFICATION_PROMPT.format(question=question, context=context)
            response = llm.invoke([HumanMessage(content=prompt)])
            
            # 解析JSON响应
            import json
            import re
            
            # 尝试提取JSON
            json_match = re.search(r'\{[^}]+\}', response.content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    "message": result.get("message", "请问您想了解什么？"),
                    "options": result.get("options", []),
                }
            
            # 默认追问
            return self._default_clarification(question)
            
        except Exception as e:
            print(f"[追问生成] 失败: {str(e)}")
            return self._default_clarification(question)

    def _default_clarification(self, question: str) -> dict:
        """默认追问模板"""
        # 根据问题关键词生成默认选项
        if any(word in question for word in ["钱", "价", "费", "多少"]):
            return {
                "message": "请问您想了解哪种套餐的价格？",
                "options": [
                    "单次体验卡",
                    "周卡",
                    "月卡"
                ],
            }
        elif any(word in question for word in ["时间", "几点", "营业"]):
            return {
                "message": "请问您想了解什么时间信息？",
                "options": [
                    "营业时间",
                    "地址位置",
                    "联系电话"
                ],
            }
        elif any(word in question for word in ["退", "换", "售后"]):
            return {
                "message": "请问您遇到了什么问题？",
                "options": [
                    "想退款",
                    "想换套餐",
                    "其他售后问题"
                ],
            }
        else:
            return {
                "message": "请问您想了解什么信息？",
                "options": [
                    "套餐价格",
                    "营业时间",
                    "退款政策",
                    "店铺规则"
                ],
            }

    def handle_clarification_response(
        self, 
        original_question: str, 
        user_response: str,
        options: list[str]
    ) -> str:
        """
        处理用户对追问的响应
        
        Args:
            original_question: 原始问题
            user_response: 用户响应
            options: 追问选项
        
        Returns:
            增强后的问题
        """
        # 简单的意图增强
        # 如果用户选择了某个选项，将其添加到问题中
        for option in options:
            # 去除选项中的价格信息
            option_text = option.split("（")[0].split("(")[0]
            if option_text in user_response or user_response in option_text:
                return f"{original_question} {option_text}"
        
        # 如果用户直接回答了问题
        return user_response


# 全局实例
_query_clarifier = None


def get_query_clarifier() -> QueryClarifier:
    """获取Query Clarifier单例"""
    global _query_clarifier
    if _query_clarifier is None:
        _query_clarifier = QueryClarifier()
    return _query_clarifier
