#!/usr/bin/env python3
"""
性能监控路由
提供性能指标、健康检查、缓存管理等功能（不含独立 chat 入口）。
"""

import asyncio
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission
from packages.auth.scope import require_tenant_admin
from backend.logging_config import get_logger
from backend.services.performance_optimizer import (
    cache_manager,
    performance_optimizer,
    stream_handler,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/performance",
    tags=["性能监控"],
    dependencies=[Depends(require_permission("chat:write"))],
)


@router.get("/metrics")
async def get_performance_metrics():
    """获取性能指标。"""
    try:
        base = await performance_optimizer.get_performance_metrics()
        cache_stats = await cache_manager.get_cache_stats()
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "metrics": {
                "performance": base,
                "cache": cache_stats,
                "active_streams": len(stream_handler.get_active_streams()),
            },
        }
    except Exception as e:
        logger.error(f"获取性能指标失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/health")
async def health_check():
    """健康检查（Redis / 缓存读写）。"""
    try:
        redis_ok = False
        cache_ok = False
        try:
            redis_ok = bool(await performance_optimizer.ping())
        except Exception:
            redis_ok = False
        try:
            test_key = "health_check_test"
            await performance_optimizer.set(test_key, "test", ttl=10)
            cache_ok = (await performance_optimizer.get(test_key)) == "test"
        except Exception:
            cache_ok = False
        checks = {"redis": redis_ok, "cache": cache_ok}
        all_healthy = all(checks.values())
        return {
            "status": "healthy" if all_healthy else "degraded",
            "checks": checks,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
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
    """获取缓存统计信息。"""
    try:
        stats = await cache_manager.get_cache_stats()
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "cache_stats": stats,
        }
    except Exception as e:
        logger.error(f"获取缓存统计失败: {e}")
        if _looks_like_redis_error(e):
            raise _redis_unavailable_http(e) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/cache/clear")
async def clear_cache(
    pattern: str | None = None,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """清除缓存（仅 tenant_admin / super_admin）。"""
    require_tenant_admin(tenant)
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
            "tenant_id": tenant.tenant_id,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"清除缓存失败: {e}")
        if _looks_like_redis_error(e):
            raise _redis_unavailable_http(e) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/streams/active")
async def get_active_streams():
    """获取活跃流信息。"""
    try:
        active_streams = stream_handler.get_active_streams()
        return {
            "status": "success",
            "active_streams": active_streams,
            "count": len(active_streams),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"获取活跃流信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/optimization/config")
async def get_optimization_config():
    """获取优化配置（缓存 TTL / 线程池）。"""
    try:
        config = {
            "cache_ttl": performance_optimizer.cache_ttl,
            "thread_pool_max_workers": performance_optimizer.thread_pool._max_workers,
        }
        return {
            "status": "success",
            "config": config,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"获取优化配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/optimization/config")
async def update_optimization_config(
    config: dict[str, Any],
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """更新优化配置（仅 tenant_admin / super_admin）。"""
    require_tenant_admin(tenant)
    try:
        if "cache_ttl" in config:
            performance_optimizer.cache_ttl = config["cache_ttl"]
        return {
            "status": "success",
            "message": "配置更新成功",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"更新优化配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/benchmark")
async def run_benchmark():
    """轻量 Redis 往返基准（不再走旁路 chat）。"""
    try:
        start_time = time.time()
        n = 10

        async def _one(i: int) -> None:
            key = f"bench:{i}"
            await performance_optimizer.set(key, f"v{i}", ttl=30)
            await performance_optimizer.get(key)

        results = await asyncio.gather(
            *[_one(i) for i in range(n)], return_exceptions=True
        )
        end_time = time.time()
        total_time = end_time - start_time
        failed = sum(1 for r in results if isinstance(r, Exception))
        successful = n - failed

        return {
            "status": "success",
            "benchmark_results": {
                "total_requests": n,
                "successful_requests": successful,
                "failed_requests": failed,
                "total_time": total_time,
                "average_time_per_request": total_time / n,
                "requests_per_second": (n / total_time) if total_time > 0 else 0.0,
                "kind": "redis_roundtrip",
            },
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"基准测试失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/system/info")
async def get_system_info():
    """获取系统信息。"""
    try:
        import platform

        import psutil

        system_info = {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(),
            "memory_total": psutil.virtual_memory().total,
            "memory_available": psutil.virtual_memory().available,
            "disk_usage": psutil.disk_usage("/").percent,
        }

        process = psutil.Process()
        process_info = {
            "pid": process.pid,
            "memory_usage": process.memory_info().rss,
            "cpu_percent": process.cpu_percent(),
            "num_threads": process.num_threads(),
        }

        return {
            "status": "success",
            "system": system_info,
            "process": process_info,
            "timestamp": datetime.now().isoformat(),
        }
    except ImportError:
        return {
            "status": "error",
            "message": "psutil not installed, cannot get system info",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"获取系统信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/")
async def performance_dashboard():
    """性能监控仪表板。"""
    try:
        metrics = await performance_optimizer.get_performance_metrics()
        cache_stats = await cache_manager.get_cache_stats()
        try:
            redis_ok = bool(await performance_optimizer.ping())
        except Exception:
            redis_ok = False
        health = {
            "status": "healthy" if redis_ok else "degraded",
            "checks": {"redis": redis_ok},
        }
        return {
            "status": "success",
            "dashboard": {
                "health": health,
                "metrics": metrics,
                "cache": cache_stats,
                "timestamp": datetime.now().isoformat(),
            },
        }
    except Exception as e:
        logger.error(f"获取性能仪表板失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
