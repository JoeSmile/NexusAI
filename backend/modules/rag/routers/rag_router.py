#!/usr/bin/env python3
"""
RAG路由
提供知识库管理和问答的API接口
"""

import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.core.errors import ContextGateException, ErrorCode
from backend.logging_config import get_logger
from backend.modules.rag.cache import bump_epoch

from ..core.knowledge_base import EnterpriseKnowledgeLoader, KnowledgeBaseManager
from ..services.rag_service import RAGIntegrationService, RAGService

logger = get_logger(__name__)

# 创建路由
router = APIRouter(prefix="/api/rag", tags=["RAG知识库"])

# 全局服务实例
_kb_manager = None
_rag_service = None
_integration_service = None


def get_kb_manager() -> KnowledgeBaseManager:
    """获取知识库管理器实例"""
    global _kb_manager
    if _kb_manager is None:
        _kb_manager = KnowledgeBaseManager()
    return _kb_manager


def get_rag_service() -> RAGService:
    """获取RAG服务实例"""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService(get_kb_manager())
    return _rag_service


def get_integration_service() -> RAGIntegrationService:
    """获取RAG集成服务实例"""
    global _integration_service
    if _integration_service is None:
        _integration_service = RAGIntegrationService(get_rag_service())
    return _integration_service


def _rag_guard(
    tenant: TenantContext = Depends(require_permission("chat:write")),
) -> TenantContext:
    """RAG 统一守卫:认证 + 请求限流(超限抛 RATE_001,由全局 handler 结构化返回)。"""
    from backend.modules.rag.cache import check_rate_limit

    check_rate_limit(tenant.tenant_id, miss=False)
    return tenant


def _rag_errors(fn):
    """端点错误统一处理:ContextGateException/HTTPException 放行,其余记日志转 500。"""
    import functools

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ContextGateException:
            raise
        except HTTPException:
            raise
        except Exception as e:
            logger.error("RAG 端点异常: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    return wrapper


# ========== 请求模型 ==========

class AskRequest(BaseModel):
    """问答请求"""
    question: str
    search_k: int = 3

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "如何查询公司的信息安全管理制度？",
                "search_k": 3
            }
        }
    )


class AskWithContextRequest(BaseModel):
    """带上下文的问答请求"""
    question: str
    conversation_history: list[dict[str, str]] | None = None
    search_k: int = 3

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "有什么具体的方法可以帮助我入睡吗？",
                "conversation_history": [
                    {"role": "user", "content": "我最近压力很大"},
                    {"role": "assistant", "content": "以下是分析结果..."}
                ],
                "search_k": 3
            }
        }
    )


class SearchRequest(BaseModel):
    """搜索请求"""
    query: str
    k: int = 3

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "焦虑应对方法",
                "k": 3
            }
        }
    )


class LoadSampleRequest(BaseModel):
    """加载示例知识请求"""
    overwrite: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "overwrite": False
            }
        }
    )


# ========== API端点 ==========

@router.get("/status")
@_rag_errors
async def get_status(
    tenant: TenantContext = Depends(_rag_guard),
):
    """
    获取知识库状态
    """
    kb_manager = get_kb_manager()
    stats = kb_manager.get_stats()
    
    return {
        "success": True,
        "data": stats
    }

@router.post("/init/sample")
@_rag_errors
async def init_sample_knowledge(
    request: LoadSampleRequest | None = None,
    tenant: TenantContext = Depends(_rag_guard),
):
    """
    初始化示例知识库
    
    加载内置的企业知识到向量数据库
    """
    tid = tenant.tenant_id
    logger.info("开始初始化示例知识库...")
    
    if request is None:
        request = LoadSampleRequest()
    
    kb_manager = get_kb_manager()
    
    # 如果要覆盖，先删除现有集合
    if request.overwrite:
        try:
            kb_manager.delete_collection()
            logger.info("已删除现有知识库")
        except Exception:
            pass
    
    # 加载示例知识
    loader = EnterpriseKnowledgeLoader(kb_manager)
    loader.load_sample_knowledge()
    bump_epoch(tid)
    
    # 获取统计信息
    stats = kb_manager.get_stats()
    
    return {
        "success": True,
        "message": "示例知识库初始化成功",
        "data": stats
    }

@router.post("/init/knowledge-base")
@_rag_errors
async def init_knowledge_base_structure(
    request: LoadSampleRequest | None = None,
    tenant: TenantContext = Depends(_rag_guard),
):
    """
    从标准知识库结构初始化知识库
    
    加载knowledge_base目录下的分类知识文档
    """
    tid = tenant.tenant_id
    logger.info("开始从知识库结构初始化...")
    
    if request is None:
        request = LoadSampleRequest()
    
    kb_manager = get_kb_manager()
    
    # 如果要覆盖，先删除现有集合
    if request.overwrite:
        try:
            kb_manager.delete_collection()
            logger.info("已删除现有知识库")
        except Exception:
            pass
    
    # 从知识库结构加载知识
    loader = EnterpriseKnowledgeLoader(kb_manager)
    loader.load_from_knowledge_base_structure()
    bump_epoch(tid)
    
    # 获取统计信息
    stats = kb_manager.get_stats()
    
    return {
        "success": True,
        "message": "知识库结构初始化成功",
        "data": stats
    }

@router.post("/upload/pdf")
@_rag_errors
async def upload_pdf(
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(_rag_guard),
):
    """
    上传PDF文档到知识库
    """
    tid = tenant.tenant_id
    logger.info(f"收到PDF上传请求: {file.filename}")
    
    # 验证文件类型
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="只支持PDF文件")
    
    # 保存临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        content = await file.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name
    
    try:
        # 加载PDF到知识库
        kb_manager = get_kb_manager()
        loader = EnterpriseKnowledgeLoader(kb_manager)
        loader.load_from_pdf(tmp_path)
        bump_epoch(tid)
        
        # 获取统计信息
        stats = kb_manager.get_stats()
        
        return {
            "success": True,
            "message": f"PDF文档 {file.filename} 已成功添加到知识库",
            "data": stats
        }
    finally:
        # 清理临时文件
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    

@router.post("/upload")
async def upload_multimodal(
    file: UploadFile = File(...),
    category: str = "general",
    tenant: TenantContext = Depends(_rag_guard),
):
    """
    统一上传：pdf / text / audio(wav|mp3|m4a) / image(png|jpg)。
    音频/图片需 `uv sync --extra multimodal`。租户取自认证上下文。
    """
    from backend.core.file_sanitizer import file_kind, sanitize_filename, validate_file
    from backend.database.vector_ops import add_knowledge
    from backend.modules.rag.extractors.audio import MultimodalDependencyError

    tenant_id = tenant.tenant_id
    content = await file.read()
    filename = file.filename or "upload.bin"
    ok, err = validate_file(filename, content, file.content_type or "")
    if not ok:
        raise ContextGateException(
            ErrorCode.FILE_INVALID_TYPE.value, err or "invalid_file"
        )

    kind = file_kind(filename) or "text"
    safe_name, ext = sanitize_filename(filename)
    tmp_path = None
    chunk_ids: list[int] = []

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext or "") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        if kind == "pdf":
            kb_manager = get_kb_manager()
            loader = EnterpriseKnowledgeLoader(kb_manager)
            loader.load_from_pdf(tmp_path)
            bump_epoch(tenant_id)
            return {
                "success": True,
                "source_type": "pdf",
                "message": f"PDF {filename} 已入库",
                "chunks": 0,
            }

        if kind == "text":
            text = content.decode("utf-8", errors="ignore").strip()
            if text:
                cid = add_knowledge(
                    text,
                    category=category,
                    tenant_id=tenant_id,
                    source=safe_name,
                    source_type="text",
                    metadata={"filename": filename},
                )
                chunk_ids.append(cid)
        elif kind == "audio":
            from backend.modules.rag.extractors.audio import extract_audio_text

            segments = extract_audio_text(tmp_path)
            for seg in segments:
                cid = add_knowledge(
                    seg["text"],
                    category=category,
                    tenant_id=tenant_id,
                    source=safe_name,
                    source_type="audio",
                    metadata={
                        "filename": filename,
                        "start": seg.get("start"),
                        "end": seg.get("end"),
                    },
                )
                chunk_ids.append(cid)
        elif kind == "image":
            from backend.modules.rag.extractors.image import extract_image_text

            text = extract_image_text(tmp_path)
            if not text:
                raise ContextGateException(
                    ErrorCode.RAG_EMPTY_EXTRACT.value, "OCR 未识别到文本"
                )
            cid = add_knowledge(
                text,
                category=category,
                tenant_id=tenant_id,
                source=safe_name,
                source_type="image",
                metadata={"filename": filename},
            )
            chunk_ids.append(cid)
        else:
            raise ContextGateException(
                ErrorCode.FILE_INVALID_TYPE.value, f"不支持的类型 {kind}"
            )

        bump_epoch(tenant_id)
        return {
            "success": True,
            "source_type": kind,
            "message": f"{filename} 已提取并写入知识库",
            "chunks": len(chunk_ids),
            "chunk_ids": chunk_ids,
        }
    except MultimodalDependencyError as e:
        raise ContextGateException(
            e.code if e.code.startswith("RAG_") else ErrorCode.RAG_DEP_MISSING.value,
            str(e),
        ) from e
    except ContextGateException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"多模态上传失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.post("/ask")
@_rag_errors
async def ask_question(
    request: AskRequest,
    tenant: TenantContext = Depends(_rag_guard),
):
    """
    向知识库提问
    
    基于知识库内容生成专业的回答
    """
    logger.info(f"收到问答请求: {request.question[:50]}...")
    
    rag_service = get_rag_service()
    result = rag_service.ask(
        question=request.question,
        search_k=request.search_k,
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
    )
    
    return {
        "success": True,
        "data": result
    }

@router.post("/ask/context")
@_rag_errors
async def ask_with_context(
    request: AskWithContextRequest,
    tenant: TenantContext = Depends(_rag_guard),
):
    """
    结合上下文的问答
    
    考虑对话历史，生成更精准的回答(不做 L1,只吃 L2 embed 缓存)
    """
    logger.info(f"收到带上下文的问答请求: {request.question[:50]}...")
    
    rag_service = get_rag_service()
    result = rag_service.ask_with_context(
        question=request.question,
        conversation_history=request.conversation_history,
        search_k=request.search_k
    )
    
    return {
        "success": True,
        "data": result
    }

@router.post("/search")
@_rag_errors
async def search_knowledge(
    request: SearchRequest,
    tenant: TenantContext = Depends(_rag_guard),
):
    """
    搜索知识库
    
    只返回相关知识片段，不生成回答
    """
    logger.info(f"收到搜索请求: {request.query[:50]}...")
    
    rag_service = get_rag_service()
    results = rag_service.search_knowledge(
        query=request.query,
        k=request.k
    )
    
    return {
        "success": True,
        "data": {
            "query": request.query,
            "results": results,
            "count": len(results)
        }
    }

@router.delete("/reset")
@_rag_errors
async def reset_knowledge_base(
    tenant: TenantContext = Depends(_rag_guard),
):
    """
    重置知识库
    
    删除所有向量数据（谨慎使用）
    """
    tid = tenant.tenant_id
    logger.warning("收到重置知识库请求 tenant=%s", tid)
    
    kb_manager = get_kb_manager()
    kb_manager.delete_collection()
    bump_epoch(tid)
    
    # 重置全局实例
    global _kb_manager, _rag_service, _integration_service
    _kb_manager = None
    _rag_service = None
    _integration_service = None
    
    return {
        "success": True,
        "message": "知识库已重置"
    }

@router.get("/test")
async def test_rag():
    """
    测试RAG功能
    
    运行一个简单的测试查询
    """
    try:
        logger.info("执行RAG测试")
        
        rag_service = get_rag_service()
        
        # 检查知识库是否可用
        if not rag_service.is_knowledge_available():
            return {
                "success": False,
                "message": "知识库未初始化或为空",
                "suggestion": "请先调用 POST /api/rag/init/sample 初始化示例知识库"
            }
        
        # 执行测试查询
        test_question = "如何查询公司的信息安全管理制度？"
        result = rag_service.ask(test_question, search_k=2)
        
        return {
            "success": True,
            "message": "RAG功能测试成功",
            "test_question": test_question,
            "test_result": {
                "answer_preview": result["answer"][:200] + "...",
                "knowledge_count": result["knowledge_count"],
                "has_sources": len(result["sources"]) > 0
            }
        }
    except Exception as e:
        logger.error(f"RAG测试失败: {e}")
        return {
            "success": False,
            "message": f"RAG测试失败: {e!s}",
            "suggestion": "请检查知识库是否正确初始化"
        }


@router.get("/examples")
async def get_examples():
    """
    获取示例问题
    
    返回一些可以测试的示例问题
    """
    examples = [
        {
            "category": "企业知识检索",
            "questions": [
                "如何查询公司的信息安全管理制度？",
                "合同审批流程是怎样的？",
                "新员工入职需要办理哪些手续？"
            ]
        },
        {
            "category": "数据与合规",
            "questions": [
                "数据脱敏有哪些要求？",
                "API Key 的管理规范是什么？",
                "敏感信息如何安全存储？"
            ]
        },
        {
            "category": "会议与文档",
            "questions": [
                "如何快速总结会议纪要？",
                "周报怎么写更清晰？",
                "项目文档如何归档？"
            ]
        },
    ]
    
    return {
        "success": True,
        "data": {
            "examples": examples,
            "usage": "选择任一问题，使用 POST /api/rag/ask 接口测试"
        }
    }


# 导出路由
__all__ = ["router"]

