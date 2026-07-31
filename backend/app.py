#!/usr/bin/env python3
"""
应用工厂
创建和配置FastAPI应用实例
"""

import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 尽早加载 config.env，保证 os.getenv 在路由/服务导入前可用（含 uvicorn 直接启动）
try:
    from dotenv import load_dotenv

    load_dotenv(Path(project_root) / "config.env")
except ImportError:
    pass

# 导入路由
from backend.pipeline.router import router as chat_pipeline_router
from backend.routers import (
    admin_router,
    audit_router,
    evaluation_router,
    feedback_router,
    memory_router,
    personalization_router,
    rag_router,
)

# 导入性能优化路由
performance_router: APIRouter | None
streaming_router: APIRouter | None
try:
    from backend.routers.performance import router as performance_router
    from backend.routers.streaming_chat import router as streaming_router
    PERFORMANCE_OPTIMIZATION_ENABLED = True
except ImportError:
    PERFORMANCE_OPTIMIZATION_ENABLED = False
    performance_router = None
    streaming_router = None

# 导入增强版聊天路由
enhanced_chat_router: APIRouter | None
try:
    from backend.routers.enhanced_chat import router as enhanced_chat_router
    ENHANCED_CHAT_ENABLED = True
except ImportError:
    ENHANCED_CHAT_ENABLED = False
    enhanced_chat_router = None

# 导入意图识别路由
intent_router: APIRouter | None
try:
    from backend.modules.intent.routers import intent_router
    INTENT_ENABLED = True
except ImportError:
    INTENT_ENABLED = False
    intent_router = None

# 尝试导入Agent路由
agent_router: APIRouter | None
try:
    from backend.routers.agent import router as agent_router
    AGENT_ENABLED = True
except ImportError:
    AGENT_ENABLED = False
    agent_router = None

# 导入日志配置
from backend.logging_config import get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """
    创建FastAPI应用实例
    
    Returns:
        配置好的FastAPI应用
    """
    # 创建应用
    app = FastAPI(
        title="ContextGate API",
        description="The Intelligent Gateway for LLM Context Management",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    from backend.core.errors import (
        ContextGateException,
        contextgate_exception_handler,
        global_exception_handler,
    )

    app.add_exception_handler(ContextGateException, contextgate_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, global_exception_handler)
    
    # CORS：浏览器不允许 allow_origins=["*"] 与 allow_credentials=True 同时使用
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

    # LIFO: 后添加的先执行 → Tenant → Metrics → Signature → CORS
    app.add_middleware(SignatureMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(TenantMiddleware)
    
    from prometheus_client import make_asgi_app

    app.mount("/metrics", make_asgi_app())

    from backend.core.health import router as health_router
    from backend.routers.files import router as files_router

    # 注册路由
    app.include_router(health_router)
    app.include_router(admin_router, prefix="/api")
    app.include_router(audit_router, prefix="/api")
    app.include_router(files_router)
    # LangGraph 管线接管 /chat（旧 chat_router 保留但不再挂载主路径）
    app.include_router(chat_pipeline_router)
    # app.include_router(chat_router)  # DEPRECATED: 使用 chat_pipeline_router
    app.include_router(memory_router)
    app.include_router(feedback_router)
    app.include_router(evaluation_router)
    app.include_router(personalization_router)
    if rag_router is not None:
        app.include_router(rag_router)
    
    # 注册增强版聊天路由（如果可用）
    if ENHANCED_CHAT_ENABLED and enhanced_chat_router:
        app.include_router(enhanced_chat_router)
        logger.info("增强版多轮对话系统已启用")
    
    # 注册Agent路由（如果可用）
    if AGENT_ENABLED and agent_router:
        app.include_router(agent_router)
        logger.info("Agent模块已启用")
    
    # 注册意图识别路由（如果可用）
    if INTENT_ENABLED and intent_router:
        app.include_router(intent_router)
        logger.info("意图识别模块已启用")
    
    # 注册性能优化路由（如果可用）
    if PERFORMANCE_OPTIMIZATION_ENABLED and performance_router:
        app.include_router(performance_router)
        logger.info("性能优化模块已启用")
    
    # 注册流式聊天路由（如果可用）
    if PERFORMANCE_OPTIMIZATION_ENABLED and streaming_router:
        app.include_router(streaming_router)
        logger.info("流式聊天模块已启用")
    
    # 根路由
    @app.get("/")
    async def root():
        """API根路径"""
        features = [
            "记忆系统",
            "上下文管理",
            "向量数据库",
            "LangChain集成",
            "自动评估",
            "RAG知识库",
            "个性化配置",
            "LangGraph管线",
        ]
        
        # 如果性能优化模块启用，添加到功能列表
        if PERFORMANCE_OPTIMIZATION_ENABLED:
            features.extend([
                "性能优化",
                "流式响应",
                "缓存机制",
                "并行处理"
            ])
        
        # 如果增强版聊天模块启用，添加到功能列表
        if ENHANCED_CHAT_ENABLED:
            features.append("增强版多轮对话")
        
        # 如果Agent模块启用，添加到功能列表
        if AGENT_ENABLED:
            features.append("Agent智能核心")
        
        # 如果意图识别模块启用，添加到功能列表
        if INTENT_ENABLED:
            features.append("意图识别系统")
        
        return {
            "name": "ContextGate",
            "version": "1.0.0",
            "status": "running",
            "features": features,
            "architecture": "分层服务架构 + Agent核心" if AGENT_ENABLED else "分层服务架构",
            "agent_enabled": AGENT_ENABLED,
            "timestamp": datetime.now().isoformat()
        }
    
    # 系统信息
    @app.get("/system/info")
    async def system_info():
        """系统信息"""
        routers_list = ["chat", "memory", "feedback", "evaluation"]
        services_list = ["ChatService", "MemoryService", "ContextService"]
        
        # 如果Agent模块启用，添加Agent相关信息
        if AGENT_ENABLED:
            routers_list.append("agent")
            services_list.append("AgentService")
        
        # 如果意图识别模块启用，添加相关信息
        if INTENT_ENABLED:
            routers_list.append("intent")
            services_list.append("IntentService")
        
        info = {
            "architecture": {
                "pattern": "分层服务架构 + Agent核心" if AGENT_ENABLED else "分层服务架构",
                "layers": ["路由层", "服务层", "核心层", "数据层"] if AGENT_ENABLED else ["路由层", "服务层", "数据层"],
                "services": services_list,
                "routers": routers_list
            },
            "memory_system": {
                "enabled": True,
                "components": ["记忆提取器", "记忆管理器", "上下文组装器"],
                "storage": ["向量数据库 (pgvector)", "关系数据库 (PostgreSQL)"]
            },
            "features": {
                "memory_extraction": "自动记忆提取",
                "context_assembly": "上下文组装",
                "user_profiling": "用户画像",
                "evaluation": "自动评估系统",
                "langgraph_pipeline": "LangGraph 管线",
                "intent_recognition": "意图识别系统" if INTENT_ENABLED else None
            }
        }
        
        # 添加Agent信息
        if AGENT_ENABLED:
            info["agent_system"] = {
                "enabled": True,
                "components": [
                    "Agent Core - 核心控制器",
                    "Memory Hub - 记忆中枢",
                    "Planner - 任务规划器",
                    "Tool Caller - 工具调用器",
                    "Reflector - 反思优化器"
                ],
                "capabilities": [
                    "智能任务规划",
                    "工具自动调用",
                    "主动回访",
                    "策略优化"
                ],
                "external_tools": [
                    "日历API",
                    "音频播放服务",
                    "心理资源数据库",
                    "定时提醒服务"
                ]
            }
        
        # 添加意图识别信息
        if INTENT_ENABLED:
            info["intent_system"] = {
                "enabled": True,
                "mode": "hybrid",
                "components": [
                    "Rule Engine - 规则引擎",
                    "ML Classifier - 机器学习分类器",
                    "Input Processor - 输入预处理器"
                ],
                "supported_intents": [
                    "emotion - 情感表达",
                    "advice - 寻求建议",
                    "conversation - 普通对话",
                    "function - 功能请求",
                    "crisis - 危机干预",
                    "chat - 闲聊"
                ],
                "capabilities": [
                    "关键词快速匹配",
                    "语义意图识别",
                    "危机情况检测",
                    "智能Prompt构建"
                ]
            }
        
        return info

    # 启动时自动发现 Skill
    try:
        from backend.skills.registry import registry

        registry.discover()
        logger.info("Skill registry: %s skills loaded", len(registry._skills))
    except Exception as e:
        logger.warning("Skill discovery failed: %s", e)

    logger.info("应用初始化完成")

    return app


# 创建应用实例
app = create_app()

