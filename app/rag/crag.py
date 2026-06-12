"""
CRAG实现（Corrective RAG）
纠正检索增强生成，确保只使用高质量文档

核心机制：
1. 文档分级：对每个检索到的文档打分（Correct/Ambiguous/Incorrect）
2. 知识精炼：从相关文档中提取关键信息
3. 纠正检索：低质量文档触发重新检索
"""

from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from app.llm import get_chat_llm


# ==================== Prompt 模板 ====================

# 1. 文档分级Prompt
DOCUMENT_GRADING_PROMPT = """你是一个文档质量评估专家。为以下文档与问题的相关性打分。

评分标准：
- Correct：文档与问题高度相关，包含回答问题所需的关键信息
- Ambiguous：文档与问题部分相关，信息不够明确或完整
- Incorrect：文档与问题无关，或包含错误/过时信息

用户问题：{question}

文档内容：
{document}

请只返回评分结果（Correct/Ambiguous/Incorrect），不要返回其他内容。"""

# 2. 知识精炼Prompt
KNOWLEDGE_REFINEMENT_PROMPT = """你是一个信息提取专家。从以下文档中提取与问题相关的关键信息。

要求：
1. 只提取与问题直接相关的信息
2. 保持信息的准确性和完整性
3. 删除无关内容和冗余信息
4. 以结构化方式组织信息

用户问题：{question}

文档内容：
{document}

请提取关键信息："""

# 3. 重新检索Prompt
REWRITE_QUERY_PROMPT = """你是一个查询优化专家。根据原始问题和检索失败的原因，生成一个更好的检索查询。

原始问题：{question}

检索失败原因：当前检索结果与问题不相关，可能是关键词不匹配或表述方式不同。

请生成一个优化后的检索查询（保持原意，但使用不同的表述方式）："""


# ==================== 文档分级枚举 ====================

class DocumentGrade:
    """文档分级结果"""
    CORRECT = "Correct"
    AMBIGUOUS = "Ambiguous"
    INCORRECT = "Incorrect"


# ==================== CRAG 核心类 ====================

class CRAG:
    """
    CRAG (Corrective RAG) 实现
    
    核心流程：
    1. 检索文档
    2. 对每个文档进行分级
    3. 高质量文档：知识精炼后使用
    4. 低质量文档：触发重新检索
    5. 混合质量：精炼高质量部分，丢弃低质量部分
    """

    def __init__(self):
        self.llm = None

    def _get_llm(self):
        """获取LLM实例"""
        if self.llm is None:
            self.llm = get_chat_llm(temperature=0)
        return self.llm

    def grade_document(self, question: str, document: str) -> str:
        """
        对文档进行分级
        
        Args:
            question: 用户问题
            document: 文档内容
        
        Returns:
            分级结果：Correct / Ambiguous / Incorrect
        """
        try:
            llm = self._get_llm()
            prompt = ChatPromptTemplate.from_template(DOCUMENT_GRADING_PROMPT)
            chain = prompt | llm
            
            response = chain.invoke({
                "question": question,
                "document": document,
            })
            
            grade = response.content.strip()
            
            # 验证返回值
            if grade in [DocumentGrade.CORRECT, DocumentGrade.AMBIGUOUS, DocumentGrade.INCORRECT]:
                return grade
            else:
                return DocumentGrade.AMBIGUOUS
                
        except Exception as e:
            print(f"[CRAG] 文档分级失败: {str(e)}")
            return DocumentGrade.AMBIGUOUS

    def refine_knowledge(self, question: str, document: str) -> str:
        """
        知识精炼：从文档中提取关键信息
        
        Args:
            question: 用户问题
            document: 文档内容
        
        Returns:
            精炼后的关键信息
        """
        try:
            llm = self._get_llm()
            prompt = ChatPromptTemplate.from_template(KNOWLEDGE_REFINEMENT_PROMPT)
            chain = prompt | llm
            
            response = chain.invoke({
                "question": question,
                "document": document,
            })
            
            return response.content.strip()
            
        except Exception as e:
            print(f"[CRAG] 知识精炼失败: {str(e)}")
            return document  # 失败时返回原文档

    def rewrite_query(self, question: str, failure_reason: str) -> str:
        """
        改写查询：用于重新检索
        
        Args:
            question: 原始问题
            failure_reason: 检索失败原因
        
        Returns:
            改写后的查询
        """
        try:
            llm = self._get_llm()
            prompt = ChatPromptTemplate.from_template(REWRITE_QUERY_PROMPT)
            chain = prompt | llm
            
            response = chain.invoke({
                "question": question,
                "failure_reason": failure_reason,
            })
            
            return response.content.strip()
            
        except Exception as e:
            print(f"[CRAG] 查询改写失败: {str(e)}")
            return question

    def process_documents(
        self, 
        question: str, 
        documents: list[Document],
        retriever_func=None
    ) -> dict:
        """
        处理文档：分级 + 精炼 + 纠正检索
        
        Args:
            question: 用户问题
            documents: 检索到的文档列表
            retriever_func: 可选的重新检索函数
        
        Returns:
            {
                "refined_context": str,
                "document_grades": list,
                "needs_retrieval": bool,
                "rewritten_query": str,
            }
        """
        if not documents:
            return {
                "refined_context": "",
                "document_grades": [],
                "needs_retrieval": True,
                "rewritten_query": question,
            }
        
        # 步骤1：对每个文档进行分级
        document_grades = []
        correct_docs = []
        ambiguous_docs = []
        incorrect_docs = []
        
        for doc in documents:
            grade = self.grade_document(question, doc.page_content)
            document_grades.append({
                "content": doc.page_content[:100],
                "grade": grade,
            })
            
            if grade == DocumentGrade.CORRECT:
                correct_docs.append(doc)
            elif grade == DocumentGrade.AMBIGUOUS:
                ambiguous_docs.append(doc)
            else:
                incorrect_docs.append(doc)
        
        print(f"[CRAG] 文档分级: Correct={len(correct_docs)}, Ambiguous={len(ambiguous_docs)}, Incorrect={len(incorrect_docs)}")
        
        # 步骤2：根据分级结果处理
        # 情况1：有 Correct 文档，直接精炼
        if correct_docs:
            refined_parts = []
            for doc in correct_docs:
                refined = self.refine_knowledge(question, doc.page_content)
                refined_parts.append(refined)
            
            # Ambiguous 部分也保留（可能有用）
            for doc in ambiguous_docs:
                refined_parts.append(doc.page_content)
            
            return {
                "refined_context": "\n\n".join(refined_parts),
                "document_grades": document_grades,
                "needs_retrieval": False,
                "rewritten_query": question,
            }
        
        # 情况2：全部是 Incorrect，需要纠正检索
        if incorrect_docs and not ambiguous_docs:
            rewritten = self.rewrite_query(question, "检索结果与问题完全不相关")
            return {
                "refined_context": "",
                "document_grades": document_grades,
                "needs_retrieval": True,
                "rewritten_query": rewritten,
            }
        
        # 情况3：只有 Ambiguous 文档，精炼使用（不再触发重新检索）
        if ambiguous_docs:
            refined_parts = []
            for doc in ambiguous_docs:
                refined = self.refine_knowledge(question, doc.page_content)
                refined_parts.append(refined)
            
            return {
                "refined_context": "\n\n".join(refined_parts),
                "document_grades": document_grades,
                "needs_retrieval": False,
                "rewritten_query": question,
            }
        
        # 情况4：无文档，需要重新检索
        return {
            "refined_context": "",
            "document_grades": document_grades,
            "needs_retrieval": True,
            "rewritten_query": question,
        }

    def correct_and_retrieve(
        self,
        question: str,
        documents: list[Document],
        retriever_func
    ) -> list[Document]:
        """
        完整的CRAG流程：分级 → 精炼 → 纠正检索
        
        Args:
            question: 用户问题
            documents: 初始检索到的文档
            retriever_func: 检索函数，接收query返回Document列表
        
        Returns:
            处理后的文档列表
        """
        # 处理文档
        result = self.process_documents(question, documents, retriever_func)
        
        # 如果需要重新检索
        if result["needs_retrieval"] and retriever_func:
            print(f"[CRAG] 触发纠正检索，改写查询: {result['rewritten_query']}")
            new_docs = retriever_func(result["rewritten_query"])
            
            # 对新检索的文档再次分级
            new_result = self.process_documents(question, new_docs)
            
            # 合并结果
            if new_result["refined_context"]:
                result["refined_context"] = new_result["refined_context"]
                result["document_grades"].extend(new_result["document_grades"])
        
        return result


# 全局实例
_crag = None


def get_crag() -> CRAG:
    """获取CRAG单例"""
    global _crag
    if _crag is None:
        _crag = CRAG()
    return _crag
