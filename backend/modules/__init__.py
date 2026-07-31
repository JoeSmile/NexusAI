"""
模块系统
包含RAG、Agent、LLM、Intent等核心模块。
包初始化不做重型导入，避免循环依赖。
"""

__all__ = ["AgentModule", "IntentService", "LLMModule", "RAGModule"]


def __getattr__(name: str):
    if name == "RAGModule":
        try:
            from .rag import RAGModule  # type: ignore

            return RAGModule
        except Exception:
            return None
    if name == "AgentModule":
        try:
            from .agent import AgentModule

            return AgentModule
        except Exception:
            return None
    if name == "LLMModule":
        try:
            from .llm import LLMModule

            return LLMModule
        except Exception:
            return None
    if name == "IntentService":
        try:
            from .intent import IntentService

            return IntentService
        except Exception:
            return None
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
