"""
路由模块 - API路由定义
"""

from apps.api.routers.ab import router as ab_router
from apps.api.routers.admin import router as admin_router
from apps.api.routers.audit import router as audit_router
from apps.api.routers.billing import router as billing_router
from apps.api.routers.evaluation import router as evaluation_router
from apps.api.routers.feedback import router as feedback_router
from apps.api.routers.memory import router as memory_router
from apps.api.routers.personalization import router as personalization_router

try:
    from packages.rag.routers.rag_router import router as rag_router
except Exception:  # pragma: no cover
    rag_router = None

try:
    from apps.api.routers.agent import router as agent_router
except Exception:  # pragma: no cover
    agent_router = None

__all__ = [
    "ab_router",
    "admin_router",
    "agent_router",
    "audit_router",
    "billing_router",
    "evaluation_router",
    "feedback_router",
    "memory_router",
    "personalization_router",
    "rag_router",
]
