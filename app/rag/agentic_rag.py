"""
Agentic RAG（增强版）
结合意图路由、混合检索、CRAG、Self-RAG、主动追问、多轮对话和实时查询

三层防幻觉：
1. CRAG：文档分级（Correct/Ambiguous/Incorrect）+ 知识精炼 + 纠正检索
2. Self-RAG：检索质量评估 + 生成质量自检 + 自反思循环
3. 意图路由 + 主动追问：低置信度时自动追问
"""

from pathlib import Path
from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from app.llm import get_chat_llm
from app.rag.intent_router import IntentRouter, IntentType, get_intent_router
from app.rag.reranker import get_reranker
from app.rag.bm25_retriever import get_bm25_retriever
from app.rag.clarification import get_query_clarifier, MAX_CLARIFICATION_ROUNDS
from app.rag.session import get_session_manager
from app.rag.realtime_checker import get_realtime_checker
from app.rag.self_rag import get_self_rag, GenerationGrade
from app.rag.crag import get_crag, DocumentGrade
from app.knowledge.package_client import get_package_client
from app.config import settings


class AgenticRAG:
    """
    Agentic RAG系统（增强版）
    
    三层防幻觉流程：
    1. CRAG：文档分级（Correct/Ambiguous/Incorrect）+ 知识精炼 + 纠正检索
    2. Self-RAG：检索质量评估 + 生成质量自检 + 自反思循环
    3. 意图路由 + 主动追问：低置信度时自动追问
    
    完整流程：
    0. 检查是否有待处理的追问
    1. 意图识别：使用LLM分析用户问题意图
    2. 判断是否需要实时查询（LLM判断）
    3. 检索：根据意图从对应知识库检索（或实时查询API）
    4. CRAG：文档分级和精炼
    5. 判断是否需要追问（低置信度时）
    6. Self-RAG：生成回答并自检
    7. 保存会话历史
    """

    def __init__(self):
        self.intent_router = get_intent_router()
        self.reranker = get_reranker()
        self.clarifier = get_query_clarifier()
        self.session_mgr = get_session_manager()
        self.realtime_checker = get_realtime_checker()
        self.package_client = get_package_client()
        self.self_rag = get_self_rag()  # Self-RAG：生成质量自检
        self.crag = get_crag()  # CRAG：文档分级和精炼
        self.intent_dirs = {
            IntentType.PACKAGE: Path("data/knowledge/package"),
            IntentType.HOURS: Path("data/knowledge/hours"),
            IntentType.REFUND: Path("data/knowledge/refund"),
            IntentType.RULES: Path("data/knowledge/rules"),
            IntentType.GENERAL: Path("data/knowledge/general"),
        }
        self._bm25_retrievers = {}

    def query(
        self, 
        question: str, 
        session_id: Optional[str] = None,
        shop_id: int = 0
    ) -> dict:
        """
        智能问答（支持CRAG + Self-RAG + 追问和多轮对话）
        
        Args:
            question: 用户问题
            session_id: 会话ID（可选）
            shop_id: 店铺ID
        
        Returns:
            {
                "type": "answer" | "clarification",
                "answer": str,  # 回答（仅type=answer时存在）
                "intent": str,  # 意图（仅type=answer时存在）
                "intent_description": str,  # 意图描述（仅type=answer时存在）
                "sources": list,  # 来源（仅type=answer时存在）
                "confidence": float,  # 置信度（仅type=answer时存在）
                "is_reliable": bool,  # 是否可靠（仅type=answer时存在）
                "self_rag_grades": dict,  # Self-RAG评估结果（仅type=answer时存在）
                "clarification": dict,  # 追问信息（仅type=clarification时存在）
            }
        """
        # 0. 检查是否有待处理的追问
        if session_id:
            pending = self.session_mgr.get_pending_clarification(session_id)
            if pending:
                # 用户正在回答追问
                return self._handle_clarification_response(
                    question, session_id, pending
                )

        # 1. 意图识别
        intent = self.intent_router.classify_intent(question)
        intent_desc = self.intent_router.get_intent_description(intent)
        
        print(f"[Agentic RAG] 意图: {intent.value} ({intent_desc})")

        # 2. 判断是否需要实时查询
        need_realtime = self.realtime_checker.need_realtime_query(question, intent)
        
        # 3. 获取套餐数据（实时查询或缓存）
        if need_realtime and intent == IntentType.PACKAGE:
            print(f"[Agentic RAG] 需要实时查询套餐数据")
            packages = self.package_client.fetch_packages(shop_id)
            
            if packages:
                # 使用实时数据生成回答
                documents = self._packages_to_documents(packages)
            else:
                print(f"[Agentic RAG] 实时查询失败，使用缓存数据")
                documents = self._retrieve_by_intent(intent, question)
        else:
            # 从缓存检索
            documents = self._retrieve_by_intent(intent, question)
        
        # 4. CRAG：文档分级和精炼
        if documents:
            print(f"[Agentic RAG] CRAG文档分级...")
            crag_result = self.crag.process_documents(
                question, 
                documents,
                retriever_func=lambda q: self._retrieve_by_intent(intent, q)
            )
            
            if crag_result["needs_retrieval"]:
                print(f"[Agentic RAG] CRAG触发纠正检索: {crag_result['rewritten_query']}")
                # 使用改写后的查询重新检索
                documents = self._retrieve_by_intent(intent, crag_result["rewritten_query"])
            elif crag_result["refined_context"]:
                # 使用精炼后的上下文
                refined_doc = Document(
                    page_content=crag_result["refined_context"],
                    metadata={"source": "crag_refined", "intent": intent.value}
                )
                documents = [refined_doc]
        
        # 5. 计算置信度
        confidence = self._calculate_confidence(documents)
        
        # 6. 获取追问次数
        clarification_count = 0
        if session_id:
            clarification_count = self.session_mgr.get_clarification_count(session_id)
        
        # 7. 判断是否需要追问
        if self.clarifier.should_clarify(confidence, clarification_count):
            # 生成追问
            sources = [
                {"content": doc.page_content[:200], "metadata": doc.metadata}
                for doc in documents
            ]
            clarification = self.clarifier.generate_clarification(question, sources)
            
            # 保存追问状态
            if session_id:
                self.session_mgr.increment_clarification_count(session_id)
                self.session_mgr.save_pending_clarification(
                    session_id, question, clarification["options"], shop_id
                )
                # 保存用户问题到历史
                self.session_mgr.add_message(session_id, "user", question)
            
            return {
                "type": "clarification",
                "clarification": clarification,
            }
        
        # 8. Self-RAG：生成回答并自检
        print(f"[Agentic RAG] Self-RAG生成回答...")
        context = "\n\n".join([doc.page_content for doc in documents[:3]])
        
        def generate_func(q, ctx):
            """生成函数，供Self-RAG调用"""
            return self._generate_answer_from_context(intent, q, ctx)
        
        self_rag_result = self.self_rag.generate_with_reflection(
            question, documents, generate_func
        )
        
        answer = self_rag_result["answer"]
        is_reliable = self_rag_result["is_reliable"]
        
        print(f"[Agentic RAG] Self-RAG结果: reliable={is_reliable}, retries={self_rag_result['retries']}")
        
        # 9. 保存会话历史
        if session_id:
            self.session_mgr.add_message(session_id, "user", question)
            self.session_mgr.add_message(session_id, "assistant", answer)
            # 重置追问次数
            self.session_mgr.reset_clarification_count(session_id)
        
        return {
            "type": "answer",
            "answer": answer,
            "intent": intent.value,
            "intent_description": intent_desc,
            "sources": [
                {
                    "content": doc.page_content[:200],
                    "metadata": doc.metadata,
                }
                for doc in documents
            ],
            "confidence": confidence,
            "is_reliable": is_reliable,
            "self_rag_grades": self_rag_result.get("grades", {}),
        }

    def _handle_clarification_response(
        self, 
        user_response: str, 
        session_id: str, 
        pending: dict
    ) -> dict:
        """
        处理用户对追问的响应
        
        Args:
            user_response: 用户响应
            session_id: 会话ID
            pending: 待处理的追问信息
        
        Returns:
            查询结果
        """
        original_question = pending["original_question"]
        options = pending["options"]
        shop_id = pending.get("shop_id", 0)  # 从pending中获取shop_id
        
        # 增强问题
        enhanced_question = self.clarifier.handle_clarification_response(
            original_question, user_response, options
        )
        
        # 清除追问状态
        self.session_mgr.clear_pending_clarification(session_id)
        self.session_mgr.reset_clarification_count(session_id)
        
        # 保存用户响应到历史
        self.session_mgr.add_message(session_id, "user", user_response)
        
        # 使用增强后的问题重新查询
        print(f"[Agentic RAG] 原始问题: {original_question}")
        print(f"[Agentic RAG] 用户响应: {user_response}")
        print(f"[Agentic RAG] 增强问题: {enhanced_question}")
        print(f"[Agentic RAG] 店铺ID: {shop_id}")
        
        # 重新查询（不传session_id，避免重复保存）
        return self.query(enhanced_question, session_id=None, shop_id=shop_id)

    def _packages_to_documents(self, packages: list[dict]) -> list[Document]:
        """
        将套餐数据转换为Document格式
        
        Args:
            packages: 套餐列表（从API获取）
        
        Returns:
            Document列表
        """
        documents = []
        
        # 套餐类型映射
        type_names = {
            "single": "单次卡",
            "weekly": "周卡",
            "monthly": "月卡",
        }
        
        # 使用次数映射
        usage_count = {
            "single": "1次",
            "weekly": "7次（每天1次，共7天）",
            "monthly": "30次（每天1次，共30天）",
        }
        
        for pkg in packages:
            pkg_type = pkg.get("type", "unknown")
            type_name = type_names.get(pkg_type, pkg_type)
            usage = usage_count.get(pkg_type, "请咨询店员")
            
            # 构建文档内容
            content = f"""## {pkg.get('name', '未知套餐')}
- **类型**：{type_name}
- **价格**：¥{pkg.get('price', 0)}
- **使用次数**：{usage}
- **单次时长**：{pkg.get('durationMinutes', 0)}分钟
- **每场上限**：{pkg.get('maxPeoplePerSession', 1)}人
"""
            if pkg.get("description"):
                content += f"- **说明**：{pkg['description']}\n"
            
            doc = Document(
                page_content=content,
                metadata={
                    "source": "api_realtime",
                    "package_id": pkg.get("id"),
                    "is_realtime": True,
                },
            )
            doc.metadata["score"] = 1.0  # 实时数据给高分
            documents.append(doc)
        
        return documents

    def _retrieve_by_intent(self, intent: IntentType, question: str) -> list[Document]:
        """根据意图从对应知识库检索（使用混合检索）"""
        try:
            from app.rag.retriever import get_hybrid_retriever
            
            # 获取混合检索器
            retriever = get_hybrid_retriever()
            
            # 使用混合检索（BM25 + 向量）
            documents = retriever.invoke(question)
            
            print(f"[Agentic RAG] 混合检索返回 {len(documents)} 个文档")
            return documents
            
        except Exception as e:
            print(f"[Agentic RAG] 混合检索失败: {str(e)}")
            # 降级到 BM25 检索
            return self._retrieve_by_bm25(intent, question)
    
    def _retrieve_by_bm25(self, intent: IntentType, question: str) -> list[Document]:
        """使用 BM25 检索（降级方案）"""
        try:
            bm25_retriever = self._get_bm25_retriever(intent)
            
            if bm25_retriever is None:
                print(f"[Agentic RAG] 意图 {intent.value} 无可用检索器")
                return []
            
            # BM25检索
            bm25_results = bm25_retriever.search(question, k=10)
            
            # 转换为Document格式
            documents = []
            for result in bm25_results:
                doc = Document(
                    page_content=result["content"],
                    metadata=result.get("metadata", {}),
                )
                doc.metadata["score"] = result.get("score", 0)
                documents.append(doc)
            
            # Reranker重排序
            if documents:
                query_data = [
                    {"content": doc.page_content, "score": doc.metadata.get("score", 0)} 
                    for doc in documents
                ]
                reranked = self.reranker.rerank(question, query_data, top_k=3)
                
                # 更新文档顺序
                documents = []
                for item in reranked:
                    doc = Document(
                        page_content=item["content"],
                        metadata=item.get("metadata", {}),
                    )
                    doc.metadata["final_score"] = item.get("rerank_score", 0)
                    documents.append(doc)
            
            return documents
            
        except Exception as e:
            print(f"[Agentic RAG] BM25 检索失败: {str(e)}")
            return []

    def _get_bm25_retriever(self, intent: IntentType):
        """获取指定意图的BM25检索器"""
        if intent in self._bm25_retrievers:
            return self._bm25_retrievers[intent]
        
        from app.rag.bm25_retriever import BM25Retriever
        
        dir_path = self.intent_dirs.get(intent)
        if dir_path is None or not dir_path.exists():
            return None
        
        # 加载该目录下的所有文档
        documents = []
        metadatas = []
        
        for file_path in dir_path.rglob("*.md"):
            try:
                content = file_path.read_text(encoding="utf-8")
                # 简单分块：按段落分块
                chunks = [chunk.strip() for chunk in content.split("\n\n") if chunk.strip()]
                
                for chunk in chunks:
                    documents.append(chunk)
                    metadatas.append({
                        "source": str(file_path),
                        "intent": intent.value,
                    })
            except Exception as e:
                print(f"[Agentic RAG] 读取文件失败: {file_path}, 错误: {e}")
        
        if not documents:
            return None
        
        # 创建BM25检索器
        retriever = BM25Retriever()
        retriever.build_index(documents, metadatas)
        self._bm25_retrievers[intent] = retriever
        
        print(f"[Agentic RAG] 为意图 {intent.value} 加载了 {len(documents)} 个文档块")
        return retriever

    def _generate_answer(self, intent: IntentType, question: str, documents: list[Document]) -> str:
        """使用意图特定的Prompt生成回答"""
        try:
            llm = get_chat_llm(temperature=0.7)
            
            # 获取意图特定的Prompt模板
            prompt_template = self.intent_router.get_prompt_for_intent(intent)
            prompt = ChatPromptTemplate.from_template(prompt_template)
            
            # 格式化文档
            context = "\n\n".join([
                f"[{i+1}] {doc.page_content}" 
                for i, doc in enumerate(documents[:3])
            ])
            
            if not context:
                context = "暂无相关信息"
            
            # 生成回答
            chain = prompt | llm
            response = chain.invoke({
                "context": context,
                "question": question,
            })
            
            return response.content
            
        except Exception as e:
            print(f"[Agentic RAG] 生成回答失败: {str(e)}")
            return f"抱歉，处理您的问题时出现错误: {str(e)}"

    def _generate_answer_from_context(self, intent: IntentType, question: str, context: str) -> str:
        """
        从上下文生成回答（供Self-RAG调用）
        
        Args:
            intent: 意图类型
            question: 用户问题
            context: 上下文内容（已精炼）
        
        Returns:
            生成的回答
        """
        try:
            llm = get_chat_llm(temperature=0.7)
            
            # 获取意图特定的Prompt模板
            prompt_template = self.intent_router.get_prompt_for_intent(intent)
            prompt = ChatPromptTemplate.from_template(prompt_template)
            
            # 生成回答
            chain = prompt | llm
            response = chain.invoke({
                "context": context,
                "question": question,
            })
            
            return response.content
            
        except Exception as e:
            print(f"[Agentic RAG] 生成回答失败: {str(e)}")
            return f"抱歉，处理您的问题时出现错误: {str(e)}"

    def _calculate_confidence(self, documents: list[Document]) -> float:
        """计算置信度"""
        if not documents:
            return 0.0
        
        scores = [doc.metadata.get("final_score", 0) for doc in documents]
        return sum(scores) / len(scores) if scores else 0.0


# 全局实例
_agentic_rag = None


def get_agentic_rag() -> AgenticRAG:
    """获取Agentic RAG单例"""
    global _agentic_rag
    if _agentic_rag is None:
        _agentic_rag = AgenticRAG()
    return _agentic_rag
