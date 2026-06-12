"""
实时查询判断器
使用LLM判断是否需要实时查询套餐数据
"""

from langchain_core.prompts import ChatPromptTemplate
from app.llm import get_chat_llm
from app.rag.intent_router import IntentType


# 实时查询判断Prompt
REALTIME_CHECK_PROMPT = """分析用户问题，判断是否需要实时查询套餐数据。

需要实时查询的情况（返回yes）：
- 用户明确问"最新套餐"、"现在有什么套餐"、"目前有哪些套餐"
- 用户质疑数据准确性（如"这个价格不对吧"、"涨价了吗"、"是不是降价了"）
- 用户问"还有没有"、"还剩多少"、"有没有新的"
- 用户问"当前"、"现在"、"最新"

不需要实时查询的情况（返回no）：
- 用户问一般性问题（如"周卡多少钱"、"月卡是什么"）
- 用户只是想了解套餐信息
- 用户在进行常规咨询

只返回 yes 或 no，不要返回其他内容。

用户问题：{question}"""


class RealtimeChecker:
    """
    实时查询判断器
    
    使用LLM分析用户问题，判断是否需要实时查询套餐数据
    """

    def __init__(self):
        self.llm = None

    def _get_llm(self):
        """获取LLM实例"""
        if self.llm is None:
            self.llm = get_chat_llm(temperature=0)  # 分类任务使用低温度
        return self.llm

    def need_realtime_query(self, question: str, intent: IntentType) -> bool:
        """
        判断是否需要实时查询
        
        Args:
            question: 用户问题
            intent: 意图类型
        
        Returns:
            是否需要实时查询
        """
        # 只有package意图才可能需要实时查询
        if intent != IntentType.PACKAGE:
            return False
        
        try:
            llm = self._get_llm()
            
            prompt = ChatPromptTemplate.from_template(REALTIME_CHECK_PROMPT)
            chain = prompt | llm
            
            response = chain.invoke({"question": question})
            result = response.content.strip().lower()
            
            need_realtime = "yes" in result
            print(f"[实时查询判断] '{question}' → {result} → {'需要实时查询' if need_realtime else '使用缓存'}")
            
            return need_realtime
            
        except Exception as e:
            print(f"[实时查询判断] 失败: {str(e)}")
            return False  # 出错时使用缓存


# 全局实例
_realtime_checker = None


def get_realtime_checker() -> RealtimeChecker:
    """获取RealtimeChecker单例"""
    global _realtime_checker
    if _realtime_checker is None:
        _realtime_checker = RealtimeChecker()
    return _realtime_checker
