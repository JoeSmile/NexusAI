#!/usr/bin/env python3
"""
性能监控路由
提供性能指标、健康检查、缓存管理等功能
"""

import asyncio
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.logging_config import get_logger
from backend.services.optimized_chat_service import optimized_chat_service
from backend.services.performance_optimizer import cache_manager, performance_optimizer

logger = get_logger(__name__)

# 创建路由器
router = APIRouter(prefix="/performance", tags=["性能监控"])


@router.get("/metrics")
async def get_performance_metrics():
    """
    获取性能指标
    
    Returns:
        性能指标数据
    """
    try:
        metrics = await optimized_chat_service.get_performance_metrics()
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "metrics": metrics
        }
    except Exception as e:
        logger.error(f"获取性能指标失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """
    健康检查
    
    Returns:
        系统健康状态
    """
    try:
        health_status = await optimized_chat_service.health_check_optimized()
        return health_status
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


def _redis_unavailable_http(exc: Exception) -> HTTPException:
    """Redis 不可达时返回结构化 503，避免裸 500（EVID-04）。"""
    from backend.core.errors import ErrorCode

    return HTTPException(
        status_code=503,
        detail={
            "code": ErrorCode.CACHE_UNAVAILABLE.value,
            "message": "redis_unavailable",
            "detail": str(exc),
        },
    )


def _looks_like_redis_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    name = exc.__class__.__name__.lower()
    needles = (
        "redis",
        "connection refused",
        "connect call failed",
        "error 61",
        "error 111",
        "6379",
        "timeout",
        "connectionerror",
    )
    return "redis" in name or any(n in msg for n in needles)


@router.get("/cache/stats")
async def get_cache_stats():
    """
    获取缓存统计信息
    
    Returns:
        缓存统计数据
    """
    try:
        stats = await cache_manager.get_cache_stats()
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "cache_stats": stats
        }
    except Exception as e:
        logger.error(f"获取缓存统计失败: {e}")
        if _looks_like_redis_error(e):
            raise _redis_unavailable_http(e) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/cache/clear")
async def clear_cache(pattern: str | None = None):
    """
    清除缓存
    
    Args:
        pattern: 缓存键模式，如果为空则清除所有缓存
        
    Returns:
        清除结果
    """
    try:
        if pattern:
            await cache_manager.invalidate_pattern(pattern)
            message = f"已清除匹配模式 '{pattern}' 的缓存"
        else:
            await cache_manager.invalidate_pattern("*")
            message = "已清除所有缓存"
        
        return {
            "status": "success",
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")
        if _looks_like_redis_error(e):
            raise _redis_unavailable_http(e) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/streams/active")
async def get_active_streams():
    """
    获取活跃流信息
    
    Returns:
        活跃流列表
    """
    try:
        from backend.services.performance_optimizer import stream_handler
        active_streams = stream_handler.get_active_streams()
        
        return {
            "status": "success",
            "active_streams": active_streams,
            "count": len(active_streams),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取活跃流信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/optimization/config")
async def get_optimization_config():
    """
    获取优化配置
    
    Returns:
        当前优化配置
    """
    try:
        config = {
            "cache_enabled": optimized_chat_service.cache_enabled,
            "max_concurrent_requests": optimized_chat_service.max_concurrent_requests,
            "request_timeout": optimized_chat_service.request_timeout,
            "cache_ttl": performance_optimizer.cache_ttl,
            "thread_pool_max_workers": performance_optimizer.thread_pool._max_workers
        }
        
        return {
            "status": "success",
            "config": config,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取优化配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimization/config")
async def update_optimization_config(config: dict[str, Any]):
    """
    更新优化配置
    
    Args:
        config: 新的配置参数
        
    Returns:
        更新结果
    """
    try:
        # 更新配置
        if "cache_enabled" in config:
            optimized_chat_service.cache_enabled = config["cache_enabled"]
        
        if "max_concurrent_requests" in config:
            optimized_chat_service.max_concurrent_requests = config["max_concurrent_requests"]
        
        if "request_timeout" in config:
            optimized_chat_service.request_timeout = config["request_timeout"]
        
        if "cache_ttl" in config:
            performance_optimizer.cache_ttl = config["cache_ttl"]
        
        return {
            "status": "success",
            "message": "配置更新成功",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"更新优化配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/benchmark")
async def run_benchmark():
    """
    运行性能基准测试
    
    Returns:
        基准测试结果
    """
    try:
        start_time = time.time()
        
        # 模拟并发请求
        test_requests = [
            {"message": f"测试消息 {i}", "session_id": f"test_{i}", "user_id": "benchmark_user"}
            for i in range(10)
        ]
        
        # 并行处理测试请求
        tasks = [
            optimized_chat_service.chat_optimized(req) 
            for req in test_requests
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # 统计结果
        successful_requests = sum(1 for r in results if not isinstance(r, Exception))
        failed_requests = len(results) - successful_requests
        
        return {
            "status": "success",
            "benchmark_results": {
                "total_requests": len(test_requests),
                "successful_requests": successful_requests,
                "failed_requests": failed_requests,
                "total_time": total_time,
                "average_time_per_request": total_time / len(test_requests),
                "requests_per_second": len(test_requests) / total_time
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"基准测试失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/system/info")
async def get_system_info():
    """
    获取系统信息
    
    Returns:
        系统信息
    """
    try:
        import platform

        import psutil
        
        # 系统信息
        system_info = {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "memory_total": psutil.virtual_memory().total,
            "memory_available": psutil.virtual_memory().available,
            "disk_usage": psutil.disk_usage('/').percent
        }
        
        # 进程信息
        process = psutil.Process()
        process_info = {
            "pid": process.pid,
            "memory_usage": process.memory_info().rss,
            "cpu_percent": process.cpu_percent(),
            "num_threads": process.num_threads()
        }
        
        return {
            "status": "success",
            "system": system_info,
            "process": process_info,
            "timestamp": datetime.now().isoformat()
        }
    except ImportError:
        return {
            "status": "error",
            "message": "psutil not installed, cannot get system info",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取系统信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def performance_dashboard():
    """
    性能监控仪表板
    
    Returns:
        综合性能信息
    """
    try:
        # 获取各种指标
        metrics = await optimized_chat_service.get_performance_metrics()
        health = await optimized_chat_service.health_check_optimized()
        cache_stats = cache_manager.get_cache_stats()
        
        return {
            "status": "success",
            "dashboard": {
                "health": health,
                "metrics": metrics,
                "cache": cache_stats,
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        logger.error(f"获取性能仪表板失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
