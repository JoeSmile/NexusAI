"""
RAG模块
检索增强生成(Retrieval-Augmented Generation)相关功能

避免在包初始化时做重型/循环导入；按需从子模块导入。
"""

__all__ = [
    "EnterpriseKnowledgeLoader",
    "KnowledgeBaseManager",
    "RAGIntegrationService",
    "RAGService",
    "rag_router",
]


def __getattr__(name: str):
    if name in ("EnterpriseKnowledgeLoader", "KnowledgeBaseManager"):
        from .core.knowledge_base import EnterpriseKnowledgeLoader, KnowledgeBaseManager

        return {
            "EnterpriseKnowledgeLoader": EnterpriseKnowledgeLoader,
            "KnowledgeBaseManager": KnowledgeBaseManager,
        }[name]
    if name in ("RAGService", "RAGIntegrationService"):
        from .services.rag_service import RAGIntegrationService, RAGService

        return {"RAGService": RAGService, "RAGIntegrationService": RAGIntegrationService}[name]
    if name == "rag_router":
        from .routers.rag_router import router

        return router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
