#!/usr/bin/env python3
"""
RAG知识库管理模块
负责企业知识文档的加载、处理、向量化和检索
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.errors import ContextGateException, ErrorCode
from backend.database import vector_ops
from backend.logging_config import get_logger

from .chunking_selector import ChunkingStrategySelector

# 使用兼容层统一处理 langchain 导入（无 Chroma）
from .langchain_compat import (
    Document,
    PyPDFLoader,
    RecursiveCharacterTextSplitter,
    TextLoader,
)

logger = get_logger(__name__)


class KnowledgeBaseManager:
    """知识库管理器"""
    
    def __init__(
        self,
        persist_directory: str = "./data/knowledge",
        chunking_strategy: str = "auto",
        chunk_size: int = 500,
        chunk_overlap: int = 50
    ):
        """
        初始化知识库管理器
        
        Args:
            persist_directory: 向量数据库持久化目录
            chunking_strategy: 分块策略（auto/recursive/structure/sentence/small_big/parent_child）
            chunk_size: 块大小（字符数）
            chunk_overlap: 块重叠（字符数）
        """
        self.persist_directory = persist_directory
        # Embedding 统一走 backend.database.embeddings.embed_text(registry + DashScope);
        # 不再初始化未使用的 LangChain OpenAIEmbeddings(Task 28)

        # Chroma 已移除；检索走 pgvector knowledge_chunks
        self.vectorstore = None
        self.chroma_client_settings = None
        self.tenant_id = "default"
        
        # 确保目录存在（文档源目录，非向量库）
        Path(persist_directory).mkdir(parents=True, exist_ok=True)
        
        # 文档分块器配置（保持向后兼容）
        if RecursiveCharacterTextSplitter is not None:
            self.text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
                separators=["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " ", ""]
            )
        else:
            self.text_splitter = None
        
        # 初始化策略选择器
        self.chunking_strategy = chunking_strategy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy_selector = ChunkingStrategySelector(
            default_strategy=chunking_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        
        logger.info(f"知识库管理器初始化完成，持久化目录: {persist_directory}, 分块策略: {chunking_strategy}")
    
    def load_pdf_documents(self, pdf_path: str) -> list[Document]:
        """
        加载单个PDF文档
        
        Args:
            pdf_path: PDF文件路径
            
        Returns:
            文档列表
        """
        try:
            logger.info(f"开始加载PDF文档: {pdf_path}")
            loader = PyPDFLoader(pdf_path)
            documents = loader.load()
            logger.info(f"成功加载PDF文档，共 {len(documents)} 页")
            return documents
        except Exception as e:
            logger.error(f"加载PDF文档失败: {e}")
            raise
    
    def load_directory_documents(self, directory_path: str, glob_pattern: str = "**/*") -> list[Document]:
        """
        批量加载目录下的文档（自动根据文件类型选择加载器）
        
        支持：PDF (.pdf), Markdown (.md), 文本 (.txt) 等格式
        
        Args:
            directory_path: 目录路径
            glob_pattern: 文件匹配模式
            
        Returns:
            文档列表
        """
        try:
            logger.info(f"开始加载目录文档: {directory_path}, 模式: {glob_pattern}")
            all_documents = []
            
            # 遍历目录下的所有匹配文件
            dir_path = Path(directory_path)
            if not dir_path.exists():
                logger.warning(f"目录不存在: {directory_path}")
                return []
            
            for file_path in dir_path.glob(glob_pattern):
                if not file_path.is_file():
                    continue
                    
                suffix = file_path.suffix.lower()
                try:
                    if suffix == '.pdf':
                        loader = PyPDFLoader(str(file_path))
                        docs = loader.load()
                    elif suffix in ('.md', '.markdown'):
                        # Markdown 文件使用 TextLoader 加载
                        loader = TextLoader(str(file_path), encoding='utf-8')
                        docs = loader.load()
                    elif suffix == '.txt':
                        loader = TextLoader(str(file_path), encoding='utf-8')
                        docs = loader.load()
                    else:
                        # 尝试作为文本文件加载
                        logger.debug(f"尝试作为文本加载未知格式文件: {file_path.name}")
                        try:
                            loader = TextLoader(str(file_path), encoding='utf-8')
                            docs = loader.load()
                        except Exception:
                            logger.warning(f"跳过不支持的文件格式: {file_path.name}")
                            continue
                    
                    # 为每个文档添加文件来源元数据
                    for doc in docs:
                        doc.metadata.setdefault('source', str(file_path))
                        doc.metadata['file_type'] = suffix
                    
                    all_documents.extend(docs)
                    logger.debug(f"成功加载文件: {file_path.name}, 共 {len(docs)} 个文档")
                    
                except Exception as e:
                    logger.warning(f"加载文件失败 {file_path.name}: {e}")
                    continue
            
            logger.info(f"成功加载目录文档，共 {len(all_documents)} 个文档")
            return all_documents
        except Exception as e:
            logger.error(f"加载目录文档失败: {e}")
            raise
    
    def load_text_documents(self, text_path: str) -> list[Document]:
        """
        加载文本文档
        
        Args:
            text_path: 文本文件路径
            
        Returns:
            文档列表
        """
        try:
            logger.info(f"开始加载文本文档: {text_path}")
            loader = TextLoader(text_path, encoding='utf-8')
            documents = loader.load()
            logger.info("成功加载文本文档")
            return documents
        except Exception as e:
            logger.error(f"加载文本文档失败: {e}")
            raise
    
    def split_documents(
        self,
        documents: list[Document],
        strategy: str | None = None
    ) -> list[Document]:
        """
        分割文档为小块
        
        Args:
            documents: 原始文档列表
            strategy: 分块策略（可选，如果为None则使用初始化时的策略）
            
        Returns:
            分割后的文档块列表
        """
        try:
            logger.info(f"开始分割文档，共 {len(documents)} 个文档")
            
            # 如果指定了策略或使用auto策略，使用策略选择器
            use_strategy_selector = (
                strategy is not None or
                self.chunking_strategy == "auto" or
                self.chunking_strategy not in ["recursive", "character", "sentence"]
            )
            
            if use_strategy_selector:
                # 使用策略选择器
                actual_strategy = strategy or self.chunking_strategy
                chunks = self.strategy_selector.split_documents(
                    documents,
                    strategy=actual_strategy
                )
            else:
                # 使用传统分块器（向后兼容）
                chunks = self.text_splitter.split_documents(documents)
            
            logger.info(f"文档分割完成，共 {len(chunks)} 个文档块")
            return chunks
        except Exception as e:
            logger.error(f"文档分割失败: {e}")
            # 如果策略选择器失败，回退到传统分块器
            logger.warning("策略选择器失败，回退到传统分块器")
            try:
                chunks = self.text_splitter.split_documents(documents)
                logger.info(f"使用传统分块器完成分割，共 {len(chunks)} 个文档块")
                return chunks
            except Exception as e2:
                logger.error(f"传统分块器也失败: {e2}")
                raise
    
    def create_vectorstore(self, chunks: list[Document]):
        """将文档块写入 pgvector knowledge_chunks"""
        try:
            logger.info(f"开始写入 pgvector 知识库，共 {len(chunks)} 个文档块")
            for i, chunk in enumerate(chunks):
                meta = dict(chunk.metadata or {})
                meta.setdefault("chunk_id", i)
                meta.setdefault("timestamp", datetime.now().isoformat())
                # 只保留简单类型
                clean_meta = {
                    k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))
                }
                vector_ops.add_knowledge(
                    text=chunk.page_content,
                    category=str(meta.get("category", "general")),
                    tenant_id=self.tenant_id,
                    metadata=clean_meta,
                )
            self.vectorstore = "pgvector"
            logger.info("pgvector 知识库写入完成")
            return self.vectorstore
        except Exception as e:
            logger.error(f"创建向量存储失败: {e}")
            raise
    
    def load_vectorstore(self):
        """pgvector 无需从目录加载；标记就绪即可"""
        self.vectorstore = "pgvector"
        logger.info("pgvector 知识库就绪")
        return self.vectorstore
    
    def add_documents(self, documents: list[Document]) -> None:
        """向 pgvector 添加文档"""
        try:
            logger.info(f"向知识库添加 {len(documents)} 个文档")
            chunks = self.split_documents(documents)
            self.create_vectorstore(chunks)
            logger.info("文档添加完成")
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            raise
    
    def search_similar(self, query: str, k: int = 3, filter: dict[str, Any] | None = None) -> list[Document]:
        """pgvector 相似度搜索"""
        try:
            logger.info(f"执行相似度搜索: {query[:50]}...")
            raw = vector_ops.search_knowledge(
                query=query, tenant_id=self.tenant_id, n_results=k
            )
            docs: list[Document] = []
            documents = (raw.get("documents") or [[]])[0]
            metadatas = (raw.get("metadatas") or [[]])[0]
            for i, content in enumerate(documents):
                meta = metadatas[i] if i < len(metadatas) else {}
                if filter:
                    if any(meta.get(fk) != fv for fk, fv in filter.items()):
                        continue
                docs.append(Document(page_content=content, metadata=meta))
            logger.info(f"搜索完成，返回 {len(docs)} 个结果")
            return docs
        except Exception as e:
            logger.error(f"相似度搜索失败: {e}")
            return []
    
    def search_with_score(self, query: str, k: int = 3) -> list[tuple[Document, float]]:
        """带评分的相似度搜索"""
        try:
            raw = vector_ops.search_knowledge(
                query=query, tenant_id=self.tenant_id, n_results=k
            )
            documents = (raw.get("documents") or [[]])[0]
            metadatas = (raw.get("metadatas") or [[]])[0]
            distances = (raw.get("distances") or [[]])[0]
            results = []
            for i, content in enumerate(documents):
                meta = metadatas[i] if i < len(metadatas) else {}
                dist = distances[i] if i < len(distances) else 1.0
                results.append((Document(page_content=content, metadata=meta), float(dist)))
            return results
        except Exception as e:
            logger.error(f"带评分的相似度搜索失败: {e}")
            return []
    
    def get_retriever(self, search_kwargs: dict[str, Any] | None = None):
        """返回简易可调用检索器（兼容 as_retriever 用法）"""
        k = (search_kwargs or {}).get("k", 3)

        class _PgRetriever:
            def __init__(self, outer, top_k):
                self.outer = outer
                self.top_k = top_k

            def get_relevant_documents(self, query: str):
                return self.outer.search_similar(query, k=self.top_k)

            def invoke(self, query: str):
                return self.get_relevant_documents(query)

        return _PgRetriever(self, k)
    
    def delete_collection(self) -> None:
        """删除当前租户知识块"""
        try:
            from backend.database.pgvector_session import KnowledgeChunk, get_pg_session

            sf = get_pg_session()
            with sf.Session() as session:
                session.query(KnowledgeChunk).filter_by(tenant_id=self.tenant_id).delete()
                session.commit()
            self.vectorstore = None
            logger.info("知识块已删除")
        except Exception as e:
            logger.error(f"删除向量集合失败: {e}")
            raise
    
    def get_stats(self) -> dict[str, Any]:
        """获取知识库统计信息"""
        try:
            from backend.database.pgvector_session import KnowledgeChunk, get_pg_session

            sf = get_pg_session()
            with sf.Session() as session:
                count = (
                    session.query(KnowledgeChunk)
                    .filter_by(tenant_id=self.tenant_id)
                    .count()
                )
            from backend.database.embeddings import embedding_model_label
            from backend.modules.rag.cache import cache_stats_snapshot

            return {
                "status": "就绪",
                "document_count": count,
                "backend": "pgvector",
                "embedding_model": embedding_model_label(),
                "cache": cache_stats_snapshot(),
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {"status": "错误", "error": str(e)}


class EnterpriseKnowledgeLoader:
    """企业知识加载器"""
    
    def __init__(self, kb_manager: KnowledgeBaseManager):
        """
        初始化知识加载器
        
        Args:
            kb_manager: 知识库管理器实例
        """
        self.kb_manager = kb_manager
        logger.info("企业知识加载器初始化完成")
    
    def load_sample_knowledge(self) -> None:
        """
        加载示例企业知识
        （当没有PDF文档时，使用预设的文本知识）
        """
        sample_texts = [
            """
            ContextGate 平台简介

            ContextGate 是企业级 LLM 信息平台网关，提供认证鉴权、多租户隔离、
            安全护栏、可观测性、模型路由与缓存能力。

            核心能力：
            1. 认证与权限：X-API-Key + RBAC 四角色（super_admin / auditor / tenant_admin / user）
            2. 安全护栏：提示注入检测、PII 脱敏、输出审查
            3. 可观测性：LangFuse 全链路 Trace
            4. 模型路由：意图驱动的短路径（Skill 直连）与长路径（LLM 生成）
            """,

            """
            API Key 安全管理

            LLM API Key 通过 AES-256-GCM 加密后存储于数据库，主密钥仅存在于环境变量。

            最佳实践：
            1. 生产环境使用 KMS 托管主密钥
            2. 按租户分配独立的 Provider Key，支持过期时间
            3. 密钥轮转通过 re_encrypt 接口完成
            4. 禁止在前端与日志中输出明文密钥
            """,

            """
            企业数据合规要点

            面向国有企业集团的 AI 平台需要满足可审计、可溯源、全链路可控的要求。

            关键措施：
            1. 全链路 Trace 记录请求与响应，支持审计回溯
            2. 租户数据物理隔离，禁止跨租户访问
            3. 敏感信息（身份证、手机号、银行卡）自动脱敏
            4. 模型调用支持数据不出域的本地化部署（vLLM / Ollama）
            """,
        ]

        for text in sample_texts:
            self.kb_manager.add_documents(
                [Document(page_content=text.strip())]
            )

    def _extract_topic(self, text: str) -> str:
        """从文本中提取主题"""
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith(' '):
                return line
        return "未知主题"
    
    def load_from_pdf(self, pdf_path: str) -> int:
        """
        从PDF文件加载知识;返回提取到文本的页数。

        扫描件/无文本层 PDF(整份提取为空)→ 抛 ContextGateException(RAG_002),
        不再静默返回"上传成功";空页(图片页)自动跳过。
        """
        try:
            logger.info(f"从PDF加载知识: {pdf_path}")

            # 加载PDF
            documents = self.kb_manager.load_pdf_documents(pdf_path)

            # 过滤空页(扫描件/图片页无文本层)
            non_empty = [d for d in documents if (d.page_content or "").strip()]
            if not non_empty:
                raise ContextGateException(
                    ErrorCode.RAG_EMPTY_EXTRACT.value,
                    "未提取到文本:扫描件或无文本层 PDF。请逐页导出为图片后走 /api/rag/upload 的 image 分支"
                    "(需 uv sync --extra multimodal),或上传带文本层的 PDF",
                )
            if len(non_empty) < len(documents):
                logger.warning(
                    "PDF %s: %d/%d 页无文本(扫描页?),已跳过空页",
                    pdf_path, len(documents) - len(non_empty), len(documents),
                )

            # 添加到知识库
            self.kb_manager.add_documents(non_empty)

            logger.info(f"成功从PDF加载知识: {pdf_path}({len(non_empty)} 页有文本)")
            return len(non_empty)

        except ContextGateException:
            raise
        except Exception as e:
            logger.error(f"从PDF加载知识失败: {e}")
            raise
    
    def load_from_directory(self, directory_path: str) -> None:
        """
        从目录批量加载知识
        
        Args:
            directory_path: 目录路径
        """
        try:
            logger.info(f"从目录批量加载知识: {directory_path}")
            
            # 加载目录下的所有PDF
            documents = self.kb_manager.load_directory_documents(directory_path)
            
            # 分割并创建向量存储
            chunks = self.kb_manager.split_documents(documents)
            self.kb_manager.create_vectorstore(chunks)
            
            logger.info(f"成功从目录加载知识: {directory_path}")
            
        except Exception as e:
            logger.error(f"从目录加载知识失败: {e}")
            raise
    
    def load_from_knowledge_base_structure(self, base_path: str = "./knowledge_base") -> None:
        """
        从标准知识库结构加载知识
        
        Args:
            base_path: 知识库根目录路径
        """
        try:
            logger.info(f"从标准知识库结构加载知识: {base_path}")
            
            all_documents = []
            
            # 定义知识库结构
            knowledge_structure = {
                "company_policies": "公司制度",
                "product_docs": "产品文档",
                "department_handbook": "部门手册",
                "compliance_guide": "合规指南",
            }
            
            for folder, category in knowledge_structure.items():
                folder_path = os.path.join(base_path, folder)
                if os.path.exists(folder_path):
                    logger.info(f"加载 {category} 知识: {folder_path}")
                    
                    # 加载该目录下的所有文档
                    try:
                        docs = self.kb_manager.load_directory_documents(
                            folder_path, 
                            glob_pattern="**/*"
                        )
                        
                        # 为每个文档添加分类元数据
                        for doc in docs:
                            doc.metadata.update({
                                "category": category,
                                "folder": folder,
                                "source": "知识库文件"
                            })
                        
                        all_documents.extend(docs)
                        logger.info(f"成功加载 {category} 知识，共 {len(docs)} 个文档")
                        
                    except Exception as e:
                        logger.warning(f"加载 {category} 知识失败: {e}")
                        continue
                else:
                    logger.warning(f"知识库目录不存在: {folder_path}")
            
            if all_documents:
                # 分割文档
                chunks = self.kb_manager.split_documents(all_documents)
                
                # 创建向量存储
                self.kb_manager.create_vectorstore(chunks)
                
                logger.info(f"成功从知识库结构加载知识，共 {len(all_documents)} 个文档，{len(chunks)} 个文档块")
            else:
                logger.warning("未找到任何知识库文档")
                
        except Exception as e:
            logger.error(f"从知识库结构加载知识失败: {e}")
            raise


if __name__ == "__main__":
    # 测试代码
    print("初始化知识库管理器...")
    kb_manager = KnowledgeBaseManager()
    
    print("加载示例知识...")
    loader = EnterpriseKnowledgeLoader(kb_manager)
    loader.load_sample_knowledge()
    
    print("\n知识库统计信息:")
    stats = kb_manager.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n测试检索功能:")
    query = "如何查询公司的信息安全管理制度？"
    print(f"查询: {query}")
    results = kb_manager.search_similar(query, k=2)
    print(f"\n找到 {len(results)} 个相关文档:")
    for i, doc in enumerate(results, 1):
        print(f"\n--- 结果 {i} ---")
        print(f"来源: {doc.metadata.get('source', '未知')}")
        print(f"主题: {doc.metadata.get('topic', '未知')}")
        print(f"内容预览: {doc.page_content[:200]}...")

