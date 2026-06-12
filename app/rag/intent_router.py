"""
意图路由器
使用LLM分析用户问题意图，路由到不同知识库
"""

from langchain_core.prompts import ChatPromptTemplate
from app.llm import get_chat_llm
from typing import Optional
from enum import Enum


class IntentType(str, Enum):
    """意图类型"""
    PACKAGE = "package"      # 套餐、价格、购买
    HOURS = "hours"          # 营业时间、地址、联系方式
    REFUND = "refund"        # 退款、退换、售后
    RULES = "rules"          # 规则、限制、要求
    GENERAL = "general"      # 其他通用问题


# 意图分类Prompt
INTENT_CLASSIFY_PROMPT = """你是一个意图分类专家。分析用户问题的意图，返回对应的类别。

可选类别：
- package: 套餐、价格、购买、周卡、月卡、次卡相关
- hours: 营业时间、地址、位置、电话、联系方式相关
- refund: 退款、退换、售后、取消订单相关
- rules: 规则、限制、要求、年龄、安全、注意事项相关
- general: 其他通用问题

只返回类别名称，不要返回其他内容。

用户问题：{question}"""


# 意图中文描述
INTENT_DESCRIPTIONS = {
    IntentType.PACKAGE: "套餐/价格/购买",
    IntentType.HOURS: "营业时间/地址/联系方式",
    IntentType.REFUND: "退款/售后",
    IntentType.RULES: "规则/限制/要求",
    IntentType.GENERAL: "通用问题",
}

# 意图对应的Prompt模板（增强防幻觉）
INTENT_PROMPTS = {
    IntentType.PACKAGE: """你是店铺套餐顾问。根据以下信息回答顾客关于套餐和价格的问题。

【重要规则】
1. 严格根据提供的信息回答，不要编造任何不存在的内容
2. 如果信息中没有相关内容，请如实说"根据现有信息，暂未找到相关说明"
3. 不要添加任何营销话术或推测性内容（如"不限次数"、"免费"等）
4. 只陈述信息中明确提到的内容

相关信息：
{context}

顾客问题：{question}

请用友好、专业的语气回答：""",

    IntentType.HOURS: """你是店铺前台助手。根据以下信息回答顾客关于营业时间和店铺信息的问题。

【重要规则】
1. 严格根据提供的信息回答，不要编造任何不存在的内容
2. 如果信息中没有相关内容，请如实说"根据现有信息，暂未找到相关说明"
3. 不要添加任何推测性内容

相关信息：
{context}

顾客问题：{question}

请用友好、专业的语气回答：""",

    IntentType.REFUND: """你是店铺售后客服。根据以下信息回答顾客关于退款和售后的问题。

【重要规则】
1. 严格根据提供的信息回答，不要编造任何不存在的内容
2. 如果信息中没有相关内容，请如实说"根据现有信息，暂未找到相关说明"
3. 退款政策以信息中明确说明的为准，不要添加其他条件

相关信息：
{context}

顾客问题：{question}

请用友好、专业的语气回答：""",

    IntentType.RULES: """你是店铺规则说明员。根据以下信息回答顾客关于店铺规则和限制的问题。

【重要规则】
1. 严格根据提供的信息回答，不要编造任何不存在的内容
2. 如果信息中没有相关内容，请如实说"根据现有信息，暂未找到相关说明"
3. 不要添加任何推测性内容

相关信息：
{context}

顾客问题：{question}

请用友好、专业的语气回答：""",

    IntentType.GENERAL: """你是店铺智能助手。根据以下信息回答顾客的问题。

【重要规则】
1. 严格根据提供的信息回答，不要编造任何不存在的内容
2. 如果信息中没有相关内容，请如实说"根据现有信息，暂未找到相关说明"
3. 不要添加任何推测性内容

相关信息：
{context}

顾客问题：{question}

请用友好、专业的语气回答：""",
}


class IntentRouter:
    """意图路由器"""

    def __init__(self):
        self.llm = None

    def _get_llm(self):
        """获取LLM实例"""
        if self.llm is None:
            self.llm = get_chat_llm(temperature=0)  # 分类任务使用低温度
        return self.llm

    def classify_intent(self, question: str) -> IntentType:
        """
        使用LLM分类用户意图
        
        Args:
            question: 用户问题
        
        Returns:
            意图类型
        """
        try:
            llm = self._get_llm()
            
            prompt = ChatPromptTemplate.from_template(INTENT_CLASSIFY_PROMPT)
            chain = prompt | llm
            
            response = chain.invoke({"question": question})
            intent_str = response.content.strip().lower()
            
            # 尝试匹配意图类型
            for intent in IntentType:
                if intent.value in intent_str:
                    print(f"[意图分类] '{question}' → {intent.value}")
                    return intent
            
            # 默认返回通用问题
            print(f"[意图分类] '{question}' → general (默认)")
            return IntentType.GENERAL
            
        except Exception as e:
            print(f"[意图分类] 失败: {str(e)}")
            return IntentType.GENERAL

    def get_prompt_for_intent(self, intent: IntentType) -> str:
        """获取意图对应的Prompt模板"""
        return INTENT_PROMPTS.get(intent, INTENT_PROMPTS[IntentType.GENERAL])

    def get_intent_description(self, intent: IntentType) -> str:
        """获取意图的中文描述"""
        return INTENT_DESCRIPTIONS.get(intent, "未知意图")


# 全局路由器实例
_intent_router = None


def get_intent_router() -> IntentRouter:
    """获取意图路由器单例"""
    global _intent_router
    if _intent_router is None:
        _intent_router = IntentRouter()
    return _intent_router
