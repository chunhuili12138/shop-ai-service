"""
Self-RAG实现
自反思检索增强生成，减少幻觉

核心机制：
1. 检索质量评估：判断检索到的文档是否相关
2. 生成内容自检：检查回答是否被检索内容支持
3. 自反思循环：不确定时自动重试，直到获得可靠答案
"""

from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from app.llm import get_chat_llm


# ==================== Prompt 模板 ====================

# 1. 检索质量评估Prompt
RETRIEVAL_EVAL_PROMPT = """你是一个检索质量评估专家。判断以下文档是否与问题相关。

评估标准：
- RELEVANT：文档与问题直接相关，包含回答问题所需的信息
- PARTIALLY_RELEVANT：文档与问题部分相关，但信息不完整
- NOT_RELEVANT：文档与问题无关

用户问题：{question}

文档内容：
{document}

请只返回评估结果（RELEVANT/PARTIALLY_RELEVANT/NOT_RELEVANT），不要返回其他内容。"""

# 2. 生成内容自检Prompt
GENERATION_EVAL_PROMPT = """你是一个回答质量评估专家。检查以下回答是否被上下文内容支持。

评估标准：
- SUPPORTED：回答中的每个事实都能在上下文中找到依据
- PARTIALLY_SUPPORTED：回答中的部分事实在上下文中有依据，部分是推测
- NOT_SUPPORTED：回答中的事实大部分是推测，上下文中没有依据

上下文内容：
{context}

生成的回答：
{answer}

请只返回评估结果（SUPPORTED/PARTIALLY_SUPPORTED/NOT_SUPPORTED），不要返回其他内容。"""

# 3. 问题可回答性评估Prompt
QUESTION_ANSWERABILITY_PROMPT = """你是一个问题分析专家。判断以下问题是否可以基于提供的上下文来回答。

评估标准：
- ANSWERABLE：上下文中有足够的信息来完整回答问题
- PARTIALLY_ANSWERABLE：上下文中有部分信息，但不足以完整回答
- NOT_ANSWERABLE：上下文中没有相关信息，无法回答

用户问题：{question}

上下文内容：
{context}

请只返回评估结果（ANSWERABLE/PARTIALLY_ANSWERABLE/NOT_ANSWERABLE），不要返回其他内容。"""


# ==================== 评估结果枚举 ====================

class RetrievalGrade:
    """检索质量评估结果"""
    RELEVANT = "RELEVANT"
    PARTIALLY_RELEVANT = "PARTIALLY_RELEVANT"
    NOT_RELEVANT = "NOT_RELEVANT"


class GenerationGrade:
    """生成内容评估结果"""
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class AnswerabilityGrade:
    """问题可回答性评估结果"""
    ANSWERABLE = "ANSWERABLE"
    PARTIALLY_ANSWERABLE = "PARTIALLY_ANSWERABLE"
    NOT_ANSWERABLE = "NOT_ANSWERABLE"


# ==================== Self-RAG 核心类 ====================

class SelfRAG:
    """
    Self-RAG 实现
    
    核心流程：
    1. 检索文档
    2. 评估检索质量（过滤不相关文档）
    3. 生成回答
    4. 评估生成质量（检查是否有依据）
    5. 不确定时重新检索或拒绝回答
    """

    def __init__(self, max_retries: int = 2):
        """
        Args:
            max_retries: 最大重试次数
        """
        self.max_retries = max_retries
        self.llm = None

    def _get_llm(self):
        """获取LLM实例"""
        if self.llm is None:
            self.llm = get_chat_llm(temperature=0)  # 评估任务使用低温度
        return self.llm

    def evaluate_retrieval(self, question: str, document: str) -> str:
        """
        评估检索质量
        
        Args:
            question: 用户问题
            document: 检索到的文档
        
        Returns:
            评估结果：RELEVANT / PARTIALLY_RELEVANT / NOT_RELEVANT
        """
        try:
            llm = self._get_llm()
            prompt = ChatPromptTemplate.from_template(RETRIEVAL_EVAL_PROMPT)
            chain = prompt | llm
            
            response = chain.invoke({
                "question": question,
                "document": document,
            })
            
            grade = response.content.strip().upper()
            
            # 验证返回值
            if grade in [RetrievalGrade.RELEVANT, RetrievalGrade.PARTIALLY_RELEVANT, RetrievalGrade.NOT_RELEVANT]:
                return grade
            else:
                # 默认返回PARTIALLY_RELEVANT
                return RetrievalGrade.PARTIALLY_RELEVANT
                
        except Exception as e:
            print(f"[Self-RAG] 检索评估失败: {str(e)}")
            return RetrievalGrade.PARTIALLY_RELEVANT

    def evaluate_generation(self, context: str, answer: str) -> str:
        """
        评估生成质量
        
        Args:
            context: 上下文内容
            answer: 生成的回答
        
        Returns:
            评估结果：SUPPORTED / PARTIALLY_SUPPORTED / NOT_SUPPORTED
        """
        try:
            llm = self._get_llm()
            prompt = ChatPromptTemplate.from_template(GENERATION_EVAL_PROMPT)
            chain = prompt | llm
            
            response = chain.invoke({
                "context": context,
                "answer": answer,
            })
            
            grade = response.content.strip().upper()
            
            # 验证返回值
            if grade in [GenerationGrade.SUPPORTED, GenerationGrade.PARTIALLY_SUPPORTED, GenerationGrade.NOT_SUPPORTED]:
                return grade
            else:
                return GenerationGrade.PARTIALLY_SUPPORTED
                
        except Exception as e:
            print(f"[Self-RAG] 生成评估失败: {str(e)}")
            return GenerationGrade.PARTIALLY_SUPPORTED

    def evaluate_answerability(self, question: str, context: str) -> str:
        """
        评估问题可回答性
        
        Args:
            question: 用户问题
            context: 上下文内容
        
        Returns:
            评估结果：ANSWERABLE / PARTIALLY_ANSWERABLE / NOT_ANSWERABLE
        """
        try:
            llm = self._get_llm()
            prompt = ChatPromptTemplate.from_template(QUESTION_ANSWERABILITY_PROMPT)
            chain = prompt | llm
            
            response = chain.invoke({
                "question": question,
                "context": context,
            })
            
            grade = response.content.strip().upper()
            
            if grade in [AnswerabilityGrade.ANSWERABLE, AnswerabilityGrade.PARTIALLY_ANSWERABLE, AnswerabilityGrade.NOT_ANSWERABLE]:
                return grade
            else:
                return AnswerabilityGrade.PARTIALLY_ANSWERABLE
                
        except Exception as e:
            print(f"[Self-RAG] 可回答性评估失败: {str(e)}")
            return AnswerabilityGrade.PARTIALLY_ANSWERABLE

    def filter_documents(self, question: str, documents: list[Document]) -> list[Document]:
        """
        过滤不相关的文档
        
        Args:
            question: 用户问题
            documents: 检索到的文档列表
        
        Returns:
            过滤后的相关文档列表
        """
        relevant_docs = []
        
        for doc in documents:
            grade = self.evaluate_retrieval(question, doc.page_content)
            
            if grade == RetrievalGrade.RELEVANT:
                doc.metadata["retrieval_grade"] = grade
                relevant_docs.append(doc)
            elif grade == RetrievalGrade.PARTIALLY_RELEVANT:
                doc.metadata["retrieval_grade"] = grade
                relevant_docs.append(doc)
            else:
                print(f"[Self-RAG] 过滤掉不相关文档: {doc.page_content[:50]}...")
        
        return relevant_docs

    def check_generation_quality(self, context: str, answer: str) -> dict:
        """
        检查生成质量
        
        Returns:
            {
                "grade": str,
                "is_acceptable": bool,
                "reason": str
            }
        """
        grade = self.evaluate_generation(context, answer)
        
        is_acceptable = grade in [GenerationGrade.SUPPORTED, GenerationGrade.PARTIALLY_SUPPORTED]
        
        reason_map = {
            GenerationGrade.SUPPORTED: "回答有充分依据",
            GenerationGrade.PARTIALLY_SUPPORTED: "回答部分有依据，部分是推测",
            GenerationGrade.NOT_SUPPORTED: "回答大部分是推测，缺乏依据",
        }
        
        return {
            "grade": grade,
            "is_acceptable": is_acceptable,
            "reason": reason_map.get(grade, "未知"),
        }

    def generate_with_reflection(
        self, 
        question: str, 
        documents: list[Document],
        generate_func
    ) -> dict:
        """
        带自反思的生成
        
        Args:
            question: 用户问题
            documents: 检索到的文档
            generate_func: 生成函数，接收(question, context)返回answer
        
        Returns:
            {
                "answer": str,
                "is_reliable": bool,
                "retries": int,
                "grades": dict
            }
        """
        # 步骤1：过滤不相关文档
        relevant_docs = self.filter_documents(question, documents)
        
        if not relevant_docs:
            return {
                "answer": "抱歉，未找到与您问题相关的信息。",
                "is_reliable": False,
                "retries": 0,
                "grades": {"retrieval": "NO_RELEVANT_DOCS"},
            }
        
        # 步骤2：检查问题可回答性
        context = "\n\n".join([doc.page_content for doc in relevant_docs])
        answerability = self.evaluate_answerability(question, context)
        
        if answerability == AnswerabilityGrade.NOT_ANSWERABLE:
            return {
                "answer": "抱歉，根据现有信息无法回答您的问题。如需帮助，请联系店铺客服。",
                "is_reliable": False,
                "retries": 0,
                "grades": {"answerability": answerability},
            }
        
        # 步骤3：生成回答并自检
        for attempt in range(self.max_retries + 1):
            # 生成回答
            answer = generate_func(question, context)
            
            # 检查生成质量
            quality = self.check_generation_quality(context, answer)
            
            print(f"[Self-RAG] 第{attempt+1}次生成，质量: {quality['grade']}")
            
            if quality["is_acceptable"]:
                return {
                    "answer": answer,
                    "is_reliable": True,
                    "retries": attempt,
                    "grades": {
                        "retrieval": relevant_docs[0].metadata.get("retrieval_grade", "UNKNOWN"),
                        "answerability": answerability,
                        "generation": quality["grade"],
                    },
                }
            
            # 不够好，继续重试
            if attempt < self.max_retries:
                print(f"[Self-RAG] 回答质量不够，准备重试...")
        
        # 重试次数用完，返回最后一次的结果
        return {
            "answer": answer,
            "is_reliable": False,
            "retries": self.max_retries,
            "grades": {
                "retrieval": relevant_docs[0].metadata.get("retrieval_grade", "UNKNOWN"),
                "answerability": answerability,
                "generation": quality["grade"],
            },
        }


# 全局实例
_self_rag = None


def get_self_rag() -> SelfRAG:
    """获取Self-RAG单例"""
    global _self_rag
    if _self_rag is None:
        _self_rag = SelfRAG()
    return _self_rag
