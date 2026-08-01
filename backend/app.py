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
    logger.info("ContextGate 启动中...")
    logger.info("═" * 40)

    try:
        from backend.database import init_database

        init_database()
        logger.info("✓ 数据库连接池就绪")
    except Exception as e:
        logger.warning("数据库初始化失败: %s", e)

    try:
        from backend.core.key_manager import KeyManager

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
        from backend.skills.registry import registry

        registry.discover()
        logger.info("Skill registry: %s skills loaded", len(registry._skills))
    except Exception as e:
        logger.warning("Skill discovery failed: %s", e)

    logger.info("═" * 40)
    logger.info("ContextGate 就绪")
    logger.info("═" * 40)

    yield

    logger.info("ContextGate 关闭中...")
    try:
        from backend.services.performance_optimizer import performance_optimizer

        await performance_optimizer.close()
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
    app = FastAPI(
        title="ContextGate API",
        description="The Intelligent Gateway for LLM Context Management",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    from backend.core.errors import (
        ContextGateException,
        contextgate_exception_handler,
        global_exception_handler,
    )

    app.add_exception_handler(ContextGateException, contextgate_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, global_exception_handler)

    _cors_all = os.getenv("CORS_ALLOW_ALL", "").strip().lower() in ("1", "true", "yes")
    if _cors_all:
        _origins = ["*"]
        _creds = False
    else:
        _extra = os.getenv("FRONTEND_ORIGINS", "")
        _origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
        if _extra:
            _origins.extend([o.strip() for o in _extra.split(",") if o.strip()])
        _origins = list(dict.fromkeys(_origins))
        _creds = True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=_creds,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from backend.core.auth.signature_auth import SignatureMiddleware
    from backend.core.metrics import MetricsMiddleware
    from backend.core.tenant import TenantMiddleware

    app.add_middleware(SignatureMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(TenantMiddleware)

    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())

    # 必选路由
    _lazy_include(app, "backend.core.health", "router", required=True)
    _lazy_include(app, "backend.routers", "admin_router", prefix="/api", required=True)
    _lazy_include(app, "backend.routers", "audit_router", prefix="/api", required=True)
    _lazy_include(app, "backend.routers.files", "router", required=True)
    _lazy_include(
        app, "backend.pipeline.router", "router", required=True, label="LangGraph 管线"
    )
    _lazy_include(app, "backend.routers", "memory_router", required=True)
    _lazy_include(app, "backend.routers", "feedback_router", required=True)
    _lazy_include(app, "backend.routers", "evaluation_router", required=True)
    _lazy_include(app, "backend.routers", "personalization_router", required=True)

    # 可选路由
    features = {
        "rag": _lazy_include(app, "backend.routers", "rag_router", label="RAG"),
        "enhanced_chat": _lazy_include(
            app,
            "backend.routers.enhanced_chat",
            "router",
            label="增强版多轮对话",
        ),
        "agent": _lazy_include(
            app, "backend.routers.agent", "router", label="Agent 模块"
        ),
        "intent": _lazy_include(
            app, "backend.modules.intent.routers", "intent_router", label="意图识别"
        ),
        "performance": _lazy_include(
            app,
            "backend.routers.performance",
            "router",
            label="性能优化",
        ),
        "streaming": _lazy_include(
            app,
            "backend.routers.streaming_chat",
            "router",
            label="流式聊天",
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
        if features.get("enhanced_chat"):
            feature_list.append("增强版多轮对话")
        if features.get("agent"):
            feature_list.append("Agent智能核心")
        if features.get("intent"):
            feature_list.append("意图识别系统")

        return {
            "name": "ContextGate",
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
        services_list = ["MemoryService", "ContextService"]
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
                "storage": ["向量数据库 (pgvector)", "关系数据库 (PostgreSQL)"],
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

    playground_dir = Path(__file__).parent.parent / "frontend"
    if playground_dir.exists():
        app.mount(
            "/playground",
            StaticFiles(directory=str(playground_dir), html=True),
            name="playground",
        )

    logger.info("应用初始化完成")
    return app


app = create_app()
