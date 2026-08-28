#!/usr/bin/env python3
"""
应用工厂
创建和配置 FastAPI 应用实例（Task 19.08 / 19.09: lazy include + lifespan）
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

try:
    from dotenv import load_dotenv

    load_dotenv(Path(project_root) / "config.env")
except ImportError:
    pass

from backend.logging_config import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动预热 / 关闭清理。"""
    logger.info("═" * 40)
    logger.info("NexusAI 启动中...")
    logger.info("═" * 40)

    try:
        from backend.database import init_database

        init_database()
        logger.info("✓ 数据库连接池就绪")
    except Exception as e:
        logger.warning("数据库初始化失败: %s", e)

    try:
        from packages.workflow.runner import (
            mark_zombie_runs_failed,
            recover_waiting_child_parents,
        )

        n = mark_zombie_runs_failed()
        if n:
            logger.warning("✓ 标记僵尸 running runs → failed: %s", n)
        r = recover_waiting_child_parents()
        if r:
            logger.info("✓ recovered waiting_child parents: %s", r)
    except Exception as e:
        logger.debug("zombie/waiting_child sweep skipped: %s", e)

    try:
        from packages.workflow.notify import start_hang_scanner

        start_hang_scanner()
        logger.info("✓ hang escalate scanner 已启动")
    except Exception as e:
        logger.debug("hang scanner skipped: %s", e)

    try:
        from packages.workflow.grant_scanner import start_grant_scanner

        start_grant_scanner()
        logger.info("✓ grant auto_renew scanner 已启动")
    except Exception as e:
        logger.debug("grant scanner skipped: %s", e)

    try:
        # I2：显式 import 注册 Prometheus gauges（不 import 不进 /metrics）
        import backend.core.metrics_memory as _metrics_memory  # noqa: F401

        logger.info("✓ memory metrics gauges registered")
    except Exception as e:
        logger.debug("memory metrics skipped: %s", e)

    try:
        from packages.workflow.scheduler import start_schedule_scanner

        start_schedule_scanner()
        logger.info("✓ workflow schedule scanner 已启动")
    except Exception as e:
        logger.debug("schedule scanner skipped: %s", e)

    try:
        from packages.key_manager import KeyManager

        KeyManager()
        logger.info("✓ KeyManager 就绪")
    except Exception as e:
        logger.warning("KeyManager 未就绪: %s", e)

    try:
        from backend.services.performance_optimizer import performance_optimizer

        r = await performance_optimizer._ensure_redis()
        if r is not None and await performance_optimizer.ping():
            logger.info("✓ Redis 连接池就绪")
        else:
            logger.info("Redis 不可用（缓存降级）")
    except Exception as e:
        logger.info("Redis 不可用（缓存降级）: %s", e)

    try:
        from packages.skills.registry import registry

        registry.discover()
        logger.info("Skill registry: %s skills loaded", len(registry._skills))
    except Exception as e:
        logger.warning("Skill discovery failed: %s", e)

    try:
        from backend.observability.langfuse_client import get_langfuse, langfuse_enabled

        if not langfuse_enabled():
            logger.info("LangFuse disabled")
        elif get_langfuse() is not None:
            logger.info("✓ LangFuse client ready")
        else:
            logger.warning("LangFuse enabled but client init failed")
    except Exception as e:
        logger.warning("LangFuse init skipped: %s", e)

    try:
        from backend.core.thread_pool import install_default_executor

        n = install_default_executor()
        logger.info("✓ default executor workers=%s", n)
    except Exception as e:
        logger.debug("default executor skipped: %s", e)

    logger.info("═" * 40)
    logger.info("NexusAI 就绪")
    logger.info("═" * 40)

    yield

    logger.info("NexusAI 关闭中...")
    try:
        from packages.workflow.notify import stop_hang_scanner

        stop_hang_scanner()
    except Exception:
        pass
    try:
        from packages.workflow.grant_scanner import stop_grant_scanner

        stop_grant_scanner()
    except Exception:
        pass
    try:
        from packages.workflow.scheduler import stop_schedule_scanner

        stop_schedule_scanner()
    except Exception:
        pass
    try:
        from backend.services.performance_optimizer import performance_optimizer

        await performance_optimizer.close()
    except Exception:
        pass
    try:
        from packages.openai_http import aclose_openai_http_clients

        await aclose_openai_http_clients()
    except Exception:
        pass
    try:
        from packages.redis_tools import close_async_redis

        await close_async_redis()
    except Exception:
        pass


def _lazy_include(
    app: FastAPI,
    module_path: str,
    attr: str,
    *,
    prefix: str | None = None,
    required: bool = False,
    label: str | None = None,
) -> bool:
    """惰性 import 并注册路由。"""
    try:
        mod = importlib.import_module(module_path)
        router = getattr(mod, attr, None)
        if router is None:
            if required:
                logger.error("必选路由缺失: %s.%s", module_path, attr)
            return False
        if prefix:
            app.include_router(router, prefix=prefix)
        else:
            app.include_router(router)
        if label:
            logger.info("%s 已启用", label)
        return True
    except Exception as e:
        if required:
            logger.error("必选路由加载失败 %s: %s", module_path, e)
            raise
        logger.debug("可选路由跳过 %s: %s", module_path, e)
        return False


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    from packages.production_guard import assert_production_security
    from packages.auth.jwt_session import assert_jwt_secret_strength

    assert_jwt_secret_strength()
    from packages.security.audit_crypto import assert_audit_encryption_config

    assert_audit_encryption_config()
    assert_production_security()

    app = FastAPI(
        title="NexusAI API",
        description="The Intelligent Gateway for LLM Context Management",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    from packages.errors import (
        NexusAIException,
        global_exception_handler,
        http_exception_audit_handler,
        nexusai_exception_handler,
    )

    app.add_exception_handler(NexusAIException, nexusai_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_audit_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, global_exception_handler)

    _cors_all = os.getenv("CORS_ALLOW_ALL", "").strip().lower() in ("1", "true", "yes")
    if _cors_all:
        _origins = ["*"]
        _creds = False
    else:
        _extra = os.getenv("CORS_ALLOW_ORIGINS") or os.getenv("FRONTEND_ORIGINS", "")
        _origins = [o.strip() for o in _extra.split(",") if o.strip()]
        _creds = bool(_origins)
    if "*" in _origins and _creds:
        raise RuntimeError(
            "CORS misconfiguration: wildcard origin with credentials is forbidden "
            "(set CORS_ALLOW_ALL=true without credentials, or list explicit origins)"
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=_creds,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from packages.metrics import MetricsMiddleware
    from packages.tenant import TenantMiddleware
    from packages.auth.signature_auth import SignatureMiddleware

    app.add_middleware(SignatureMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(TenantMiddleware)

    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())

    # 必选路由
    _lazy_include(app, "backend.core.health", "router", required=True)
    _lazy_include(app, "apps.api.routers", "admin_router", prefix="/api", required=True)
    _lazy_include(
        app,
        "apps.api.routers.admin_console",
        "router",
        prefix="/api",
        required=True,
        label="Admin Console",
    )
    _lazy_include(app, "apps.api.routers", "ab_router", prefix="/api", required=True)
    _lazy_include(app, "apps.api.routers", "audit_router", prefix="/api", required=True)
    _lazy_include(app, "apps.api.routers", "billing_router", prefix="/api", required=True)
    _lazy_include(
        app,
        "apps.api.routers.terms",
        "router",
        prefix="/api",
        required=True,
        label="Terms",
    )
    _lazy_include(
        app,
        "apps.api.routers.multimodal",
        "router",
        prefix="/api",
        required=True,
        label="Multimodal",
    )
    _lazy_include(app, "apps.api.routers.files", "router", required=True)
    _lazy_include(
        app, "packages.pipeline.router", "router", required=True, label="LangGraph 管线"
    )
    _lazy_include(
        app,
        "apps.api.routers.chat_history",
        "router",
        required=True,
        label="Chat 历史",
    )
    _lazy_include(
        app,
        "apps.api.routers.plan_snapshot",
        "router",
        required=True,
        label="Chat 执行快照",
    )
    _lazy_include(app, "apps.api.routers", "memory_router", required=True)
    _lazy_include(app, "apps.api.routers", "feedback_router", required=True)
    _lazy_include(app, "apps.api.routers", "evaluation_router", required=True)
    _lazy_include(app, "apps.api.routers", "personalization_router", required=True)
    _lazy_include(
        app, "apps.api.routers.auth", "router", label="账号认证", required=True
    )
    _lazy_include(
        app,
        "apps.api.routers.org",
        "router",
        prefix="/api",
        required=True,
        label="组织 Org",
    )
    _lazy_include(
        app,
        "apps.api.routers.workflows",
        "router",
        prefix="/api",
        required=True,
        label="Workflow 定义",
    )
    _lazy_include(
        app,
        "apps.api.routers.workflow_runs",
        "router",
        prefix="/api",
        required=True,
        label="Workflow Runs",
    )
    _lazy_include(
        app,
        "apps.api.routers.workflow_approvals",
        "router",
        prefix="/api",
        required=True,
        label="Workflow Approvals",
    )
    _lazy_include(
        app,
        "apps.api.routers.tenant_subscription",
        "router",
        label="Tenant Subscription",
    )
    _lazy_include(
        app,
        "apps.api.routers.content_ops",
        "router",
        required=True,
        label="Content ops / offerings",
    )
    _lazy_include(
        app,
        "apps.api.routers.social",
        "router",
        required=True,
        label="Social benchmark (TikHub)",
    )
    _lazy_include(
        app,
        "apps.api.routers.llm_public",
        "router",
        prefix="/api",
        required=True,
        label="LLM public models",
    )
    _lazy_include(
        app,
        "apps.api.routers.notifications",
        "router",
        prefix="/api",
        required=True,
        label="Notifications",
    )
    _lazy_include(
        app,
        "apps.api.routers.channel_webhooks",
        "router",
        required=True,
        label="Channel webhooks",
    )

    # 可选路由
    features = {
        "rag": _lazy_include(app, "apps.api.routers", "rag_router", label="RAG"),
        "agent": _lazy_include(
            app, "apps.api.routers.agent", "router", label="Agent 模块"
        ),
        "intent": _lazy_include(
            app, "packages.intent.routers", "intent_router", label="意图识别"
        ),
        "performance": _lazy_include(
            app,
            "apps.api.routers.performance",
            "router",
            label="性能优化",
        ),
        "capabilities": _lazy_include(
            app,
            "apps.api.routers.capability",
            "router",
            label="Capability Hub",
        ),
        "agents": _lazy_include(
            app,
            "apps.api.routers.agents",
            "router",
            label="Agent 市场",
        ),
    }
    app.state.feature_flags = features

    @app.get("/")
    async def root():
        feature_list = [
            "记忆系统",
            "上下文管理",
            "向量数据库",
            "LangChain集成",
            "自动评估",
            "个性化配置",
            "LangGraph管线",
        ]
        if features.get("rag"):
            feature_list.append("RAG知识库")
        if features.get("performance"):
            feature_list.extend(["性能优化", "流式响应", "缓存机制", "并行处理"])
        if features.get("agent"):
            feature_list.append("Agent智能核心")
        if features.get("intent"):
            feature_list.append("意图识别系统")
        if features.get("capabilities"):
            feature_list.append("Capability Hub")

        return {
            "name": "NexusAI",
            "version": "1.0.0",
            "status": "running",
            "features": feature_list,
            "architecture": (
                "分层服务架构 + Agent核心"
                if features.get("agent")
                else "分层服务架构"
            ),
            "agent_enabled": bool(features.get("agent")),
            "timestamp": datetime.now().isoformat(),
        }

    @app.get("/system/info")
    async def system_info():
        routers_list = ["chat", "memory", "feedback", "evaluation"]
        services_list = ["UnifiedMemoryService", "ContextService"]
        if features.get("agent"):
            routers_list.append("agent")
            services_list.append("AgentService")
        if features.get("intent"):
            routers_list.append("intent")
            services_list.append("IntentService")

        return {
            "architecture": {
                "pattern": (
                    "分层服务架构 + Agent核心"
                    if features.get("agent")
                    else "分层服务架构"
                ),
                "layers": (
                    ["路由层", "服务层", "核心层", "数据层"]
                    if features.get("agent")
                    else ["路由层", "服务层", "数据层"]
                ),
                "services": services_list,
                "routers": routers_list,
            },
            "memory_system": {
                "enabled": True,
                "components": ["记忆提取器", "记忆管理器", "上下文组装器"],
                "storage": ["PostgreSQL 单库(pgvector 扩展承载向量列,与关系表同库)"],
            },
            "features": {
                "memory_extraction": "自动记忆提取",
                "context_assembly": "上下文组装",
                "user_profiling": "用户画像",
                "evaluation": "自动评估系统",
                "langgraph_pipeline": "LangGraph 管线",
                "intent_recognition": (
                    "意图识别系统" if features.get("intent") else None
                ),
            },
        }

    from fastapi.staticfiles import StaticFiles

    playground_dir = Path(__file__).parent.parent / "examples"
    if playground_dir.exists():
        app.mount(
            "/playground",
            StaticFiles(directory=str(playground_dir), html=True),
            name="playground",
        )

    logger.info("应用初始化完成")
    return app


app = create_app()
