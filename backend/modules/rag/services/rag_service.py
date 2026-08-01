#!/usr/bin/env python3
"""
RAG服务层
负责检索增强生成的业务逻辑
"""

from typing import Any

# 使用兼容层处理 langchain 导入

try:
    from langchain.chains import RetrievalQA
except ImportError:  # pragma: no cover
    try:
        from langchain.chains.retrieval_qa.base import RetrievalQA
    except ImportError:
        RetrievalQA = None

try:
    from langchain_core.prompts import PromptTemplate
except ImportError:  # pragma: no cover
    PromptTemplate = None

from backend.logging_config import get_logger
from backend.modules.llm.harness import try_create_chat_openai
from config import Config

from ..core.knowledge_base import KnowledgeBaseManager

logger = get_logger(__name__)


class RAGService:
    """RAG检索增强生成服务"""
    
    def __init__(self, kb_manager: KnowledgeBaseManager | None = None):
        """
        初始化RAG服务
        
        Args:
            kb_manager: 知识库管理器实例
        """
        if kb_manager is None:
            kb_manager = KnowledgeBaseManager()
            # 尝试加载已存在的向量存储
            try:
                kb_manager.load_vectorstore()
            except Exception as e:
                logger.warning(f"加载向量存储失败，可能需要先初始化知识库: {e}")
        
        self.kb_manager = kb_manager
        self.llm = try_create_chat_openai(temperature=0.7)
        if self.llm is None:
            logger.warning("RAG: LLM Harness 未能创建 ChatOpenAI，部分 RAG 能力不可用")
        
        # RAG 通用 prompt 模板
        self.prompt_template = PromptTemplate(
            template="""你是"ContextGate"，企业级 LLM 信息平台的智能助手。你正在使用企业知识库来回答用户的问题。

参考知识：
{context}

用户问题：{question}

请基于上述知识，用专业、准确的语气回答用户。注意：
1. 优先使用知识库中的内容作为依据
2. 用通俗易懂的语言解释专业概念
3. 提供具体可操作的信息
4. 知识库中没有依据时明确说明，不编造
5. 回答简洁并标注来源（如有）

回答：""",
            input_variables=["context", "question"]
        )
        
        logger.info("RAG服务初始化完成")
    
    def create_qa_chain(self, search_k: int = 3) -> RetrievalQA:
        """
        创建QA链
        
        Args:
            search_k: 检索文档数量
            
        Returns:
            QA链实例
        """
        if self.llm is None:
            raise RuntimeError("RAG 需要可用的 LLM，请在 config.env 中配置 LLM_API_KEY 与 LLM_BASE_URL")
        try:
            retriever = self.kb_manager.get_retriever(search_kwargs={"k": search_k})
            
            qa_chain = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type="stuff",
                retriever=retriever,
                return_source_documents=True,
                chain_type_kwargs={
                    "prompt": self.prompt_template
                }
            )
            
            logger.info(f"QA链创建成功，检索数量: {search_k}")
            return qa_chain
            
        except Exception as e:
            logger.error(f"创建QA链失败: {e}")
            raise
    
    def _hyde_hypothesis(self, question: str) -> str | None:
        """用 LLM 生成简短假设文档（HyDE）；失败返回 None。"""
        if self.llm is None:
            return None
        try:
            prompt = (
                "请用 2-3 句中文写一段可能回答下列问题的企业知识片段"
                "（制度/流程口吻，不要提问）:\n"
                f"问题: {question}"
            )
            resp = self.llm.invoke(prompt)
            text = getattr(resp, "content", None) or str(resp)
            text = (text or "").strip()
            return text or None
        except Exception as e:
            logger.warning("HyDE 假设文档生成失败: %s", e)
            return None

    def _doc_key(self, doc) -> str:
        meta = getattr(doc, "metadata", None) or {}
        mid = meta.get("id") or meta.get("chunk_id") or meta.get("source")
        if mid is not None:
            return f"id:{mid}"
        content = getattr(doc, "page_content", "") or ""
        return f"c:{hash(content[:200])}"

    def _merge_docs(self, *doc_lists) -> list:
        seen: set[str] = set()
        merged = []
        for docs in doc_lists:
            for doc in docs or []:
                key = self._doc_key(doc)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(doc)
        return merged

    def _llm_rerank(self, question: str, docs: list, top_n: int) -> list:
        """轻量 LLM 打分重排；失败则截断原序。"""
        if not docs or self.llm is None:
            return docs[:top_n]
        try:
            lines = []
            for i, doc in enumerate(docs):
                snippet = (doc.page_content or "")[:280].replace("\n", " ")
                lines.append(f"[{i}] {snippet}")
            prompt = (
                "你是检索重排器。根据与问题的相关性，输出最多 "
                f"{top_n} 个文档编号，JSON 数组，例如 [2,0,5]。\n"
                f"问题: {question}\n候选:\n" + "\n".join(lines)
            )
            resp = self.llm.invoke(prompt)
            text = getattr(resp, "content", None) or str(resp)
            import json
            import re

            match = re.search(r"\[[^\]]+\]", text or "")
            if not match:
                return docs[:top_n]
            order = json.loads(match.group(0))
            ranked = []
            for idx in order:
                if isinstance(idx, int) and 0 <= idx < len(docs):
                    ranked.append(docs[idx])
                if len(ranked) >= top_n:
                    break
            if ranked:
                return ranked
        except Exception as e:
            logger.warning("LLM rerank 失败，降级截断: %s", e)
        return docs[:top_n]

    def retrieve_documents(self, question: str, search_k: int = 3) -> list:
        """HyDE 双路召回 + 可选 LLM ReRank。"""
        hyde_on = bool(getattr(Config, "RAG_HYDE_ENABLED", False))
        rerank_on = bool(getattr(Config, "RAG_RERANK_ENABLED", False))
        pool = int(getattr(Config, "RAG_RERANK_POOL_SIZE", 20) or 20)
        fetch_k = pool if (hyde_on or rerank_on) else search_k

        primary = self.kb_manager.search_similar(question, k=fetch_k)
        docs = list(primary)

        if hyde_on:
            hypo = self._hyde_hypothesis(question)
            if hypo:
                secondary = self.kb_manager.search_similar(hypo, k=fetch_k)
                docs = self._merge_docs(primary, secondary)
                logger.info(
                    "HyDE 双路召回: primary=%s secondary=%s merged=%s",
                    len(primary),
                    len(secondary),
                    len(docs),
                )

        if rerank_on and docs:
            docs = self._llm_rerank(question, docs, top_n=search_k)
        else:
            docs = docs[:search_k]
        return docs

    def ask(self, question: str, search_k: int = 3) -> dict[str, Any]:
        """
        向知识库提问（支持 HyDE + LLM ReRank，由 config 开关控制）
        """
        try:
            logger.info(f"收到问题: {question[:50]}...")
            source_documents = self.retrieve_documents(question, search_k=search_k)

            if self.llm is None:
                raise RuntimeError(
                    "RAG 需要可用的 LLM，请在 config.env 中配置 LLM_API_KEY 与 LLM_BASE_URL"
                )

            context = "\n\n".join(
                d.page_content for d in source_documents if getattr(d, "page_content", None)
            )
            prompt = self.prompt_template.format(context=context or "（无检索结果）", question=question)
            resp = self.llm.invoke(prompt)
            answer = getattr(resp, "content", None) or str(resp)

            sources = []
            for doc in source_documents:
                content = doc.page_content or ""
                sources.append(
                    {
                        "content": content[:200] + "..." if len(content) > 200 else content,
                        "metadata": doc.metadata,
                    }
                )

            logger.info(f"回答生成成功，使用了 {len(sources)} 个知识源")
            return {
                "answer": answer,
                "sources": sources,
                "question": question,
                "knowledge_count": len(sources),
            }

        except Exception as e:
            logger.error(f"回答问题失败: {e}")
            raise
    
    def search_knowledge(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        """
        仅搜索知识库，不生成回答
        
        Args:
            query: 查询文本
            k: 返回结果数量
            
        Returns:
            搜索结果列表
        """
        try:
            logger.info(f"搜索知识库: {query[:50]}...")
            
            # 带评分的搜索
            results = self.kb_manager.search_with_score(query, k=k)
            
            # 整理结果
            formatted_results = []
            for doc, score in results:
                result = {
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "relevance_score": float(score)
                }
                formatted_results.append(result)
            
            logger.info(f"搜索完成，返回 {len(formatted_results)} 个结果")
            return formatted_results
            
        except Exception as e:
            logger.error(f"搜索知识库失败: {e}")
            raise
    
    def ask_with_context(
        self,
        question: str,
        conversation_history: list[dict[str, str]] | None = None,
        search_k: int = 3
    ) -> dict[str, Any]:
        """
        结合对话上下文的知识问答
        
        Args:
            question: 用户问题
            conversation_history: 对话历史
                search_k: 检索文档数量
            
        Returns:
            包含答案和来源的字典
        """
        if self.llm is None:
            raise RuntimeError("RAG 需要可用的 LLM，请在 config.env 中配置 LLM_API_KEY 与 LLM_BASE_URL")
        try:
            logger.info(f"结合上下文回答问题: {question[:50]}...")
            
            # HyDE + LLM ReRank（与 ask() 共用；默认关闭，见 RAG_*_ENABLED）
            knowledge_docs = self.retrieve_documents(question, search_k=search_k)

            # 构建增强的上下文
            knowledge_context = "\n\n".join([
                f"【知识{i+1}】{doc.page_content}"
                for i, doc in enumerate(knowledge_docs)
            ])
            
            # 构建对话历史上下文
            history_context = ""
            if conversation_history:
                recent_history = conversation_history[-3:]  # 只使用最近3轮对话
                history_lines = []
                for msg in recent_history:
                    role = "用户" if msg.get("role") == "user" else "ContextGate"
                    content = msg.get("content", "")
                    history_lines.append(f"{role}: {content}")
                history_context = "\n".join(history_lines)
            
            # 构建完整的prompt
            enhanced_prompt = f"""你是"ContextGate"，企业级 LLM 信息平台的智能助手。


最近对话：
{history_context}

参考的企业知识：
{knowledge_context}

用户当前问题：{question}

请基于上述知识和对话上下文，用专业、准确的语气回答用户。注意：
1. 结合用户上下文给出准确回答
2. 结合对话历史，提供连贯的回应
3. 优先使用知识库中的内容作为依据
4. 用通俗易懂的语言解释专业概念
5. 提供具体可操作的信息
6. 知识库无依据时明确说明，不编造

回答："""
            
            # 使用LLM生成回答
            response = self.llm.predict(enhanced_prompt)
            
            # 整理来源信息
            sources = []
            for doc in knowledge_docs:
                source_info = {
                    "content": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content,
                    "metadata": doc.metadata
                }
                sources.append(source_info)
            
            logger.info("结合上下文的回答生成成功")
            
            return {
                "answer": response,
                "sources": sources,
                "question": question,
                "knowledge_count": len(sources),
                    "used_history_context": conversation_history is not None
            }
            
        except Exception as e:
            logger.error(f"结合上下文回答失败: {e}")
            raise
    
    def get_knowledge_stats(self) -> dict[str, Any]:
        """
        获取知识库统计信息
        
        Returns:
            统计信息字典
        """
        try:
            return self.kb_manager.get_stats()
        except Exception as e:
            logger.error(f"获取知识库统计信息失败: {e}")
            return {"error": str(e)}
    
    def is_knowledge_available(self) -> bool:
        """
        检查知识库是否可用，如果不可用则尝试自动初始化
        
        Returns:
            是否可用
        """
        try:
            stats = self.kb_manager.get_stats()
            if stats.get("status") == "就绪" and stats.get("document_count", 0) > 0:
                return True
            
            # 如果知识库未初始化，尝试自动初始化
            logger.info("知识库未初始化，尝试自动加载示例知识...")
            try:
                from ..core.knowledge_base import EnterpriseKnowledgeLoader
                loader = EnterpriseKnowledgeLoader(self.kb_manager)
                loader.load_sample_knowledge()
                
                # 再次检查
                stats = self.kb_manager.get_stats()
                if stats.get("status") == "就绪" and stats.get("document_count", 0) > 0:
                    logger.info(f"知识库自动初始化成功，文档数: {stats.get('document_count', 0)}")
                    return True
                else:
                    logger.warning("知识库自动初始化后仍不可用")
                    return False
            except Exception as e:
                logger.warning(f"知识库自动初始化失败: {e}")
                return False
        except Exception as e:
            logger.error(f"检查知识库可用性时出错: {e}")
            return False


class RAGIntegrationService:
    """RAG集成服务 - 将RAG功能集成到ContextGate机器人"""
    
    def __init__(self, rag_service: RAGService | None = None):
        """
        初始化RAG集成服务
        
        Args:
            rag_service: RAG服务实例
        """
        self.rag_service = rag_service or RAGService()
        logger.info("RAG集成服务初始化完成")
    
    def should_use_rag(self, message: str) -> bool:
        """
        判断是否应该使用RAG
        
        Args:
            message: 用户消息
                
        Returns:
            是否使用RAG
        """
        # 检查知识库是否可用
        if not self.rag_service.is_knowledge_available():
            return False
            
        # 优先使用大模型进行意图分类判断
        try:
            prompt = f"""
            判断以下用户的问题是否需要企业知识库中的专业知识来回答。
            用户输入: "{message}"
                如果需要引入知识库内容提供建议，请回复 "True"；如果只是普通的闲聊或寒暄，请回复 "False"。
            仅回复 "True" 或 "False"。
            """
            
            # 使用 LLM 进行分类 (基于现有 llm_core 或直接调用 self.rag_service.llm)
            decision = self.rag_service.llm.invoke(prompt).content.strip()
            is_rag_needed = "true" in decision.lower()
            logger.info(f"LLM 意图判断 RAG 分类: {decision} -> {is_rag_needed}")
            if is_rag_needed:
                return True
        except Exception as e:
            logger.warning(f"LLM 意图分类判断失败，回退至关键词检测: {e}")
        
        # Fallback 到原有的关键词方法
        rag_triggers = [
            "怎么办", "如何", "方法", "建议", "技巧", "练习",
            "文档", "方案", "流程", "规范", "报告", "分析", "总结",
            "合同", "数据", "指标", "政策", "制度", "部署", "配置"
        ]
        
        message_lower = message.lower()
        has_trigger = any(trigger in message_lower for trigger in rag_triggers)
            
        should_use = has_trigger
        
        if should_use:
            logger.info(f"触发RAG(关键词回退): trigger={has_trigger}")
        
        return should_use
    
    def enhance_response(
        self,
        message: str,
        conversation_history: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        """
        增强回复 - 结合知识库生成更专业的回答
        
        Args:
            message: 用户消息
                conversation_history: 对话历史
            
        Returns:
            增强的回复字典
        """
        try:
            # 判断是否应该使用RAG
            if not self.should_use_rag(message):
                return {
                    "use_rag": False,
                    "reason": "当前对话不需要专业知识库支持"
                }
            
            # 使用RAG生成回答
            result = self.rag_service.ask_with_context(
                question=message,
                conversation_history=conversation_history,
                search_k=3
            )
            
            result["use_rag"] = True
            return result
            
        except Exception as e:
            logger.error(f"增强回复失败: {e}")
            return {
                "use_rag": False,
                "error": str(e)
            }


if __name__ == "__main__":
    # 测试代码
    print("初始化RAG服务...")
    rag_service = RAGService()
    
    print("\n知识库状态:")
    stats = rag_service.get_knowledge_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n测试问答:")
    question = "如何查询公司的信息安全管理制度？"
    print(f"问题: {question}")
    
    try:
        result = rag_service.ask(question)
        print(f"\n回答:\n{result['answer']}")
        print(f"\n使用了 {result['knowledge_count']} 个知识源")
        print("\n知识来源:")
        for i, source in enumerate(result['sources'], 1):
            print(f"\n来源{i}:")
            print(f"  主题: {source['metadata'].get('topic', '未知')}")
            print(f"  内容: {source['content']}")
    except Exception as e:
        print(f"错误: {e}")
        print("提示: 可能需要先初始化知识库")

