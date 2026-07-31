"""
路由模块 - API路由定义
"""

from backend.routers.chat import router as chat_router
from backend.routers.memory import router as memory_router
from backend.routers.feedback import router as feedback_router
from backend.routers.evaluation import router as evaluation_router
from backend.routers.personalization import router as personalization_router
from backend.routers.admin import router as admin_router
from backend.routers.audit import router as audit_router

try:
    from backend.modules.rag.routers.rag_router import router as rag_router
except Exception:  # pragma: no cover
    rag_router = None

try:
    from backend.routers.agent import router as agent_router
except Exception:  # pragma: no cover
    agent_router = None

__all__ = [
    "admin_router",
    "audit_router",
    "chat_router",
    "memory_router",
    "feedback_router",
    "evaluation_router",
    "personalization_router",
    "rag_router",
    "agent_router",
]
