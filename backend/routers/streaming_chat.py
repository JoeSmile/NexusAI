#!/usr/bin/env python3
"""已废弃——流式聊天请走 ``POST /chat/streaming``（LangGraph 管线）。

``/streaming/*`` 仅兼容保留；物理删除见 Task 32+（能力化收口）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from backend.logging_config import get_logger
from backend.services.optimized_chat_service import optimized_chat_service

logger = get_logger(__name__)

router = APIRouter(prefix="/streaming", tags=["流式聊天"])

_DEP_TRUE = "true"


def _dep_headers(successor: str) -> dict[str, str]:
    return {
        "Deprecation": _DEP_TRUE,
        "Link": f'<{successor}>; rel="successor-version"',
    }


def _stamp_streaming(resp: StreamingResponse, successor: str) -> StreamingResponse:
    for k, v in _dep_headers(successor).items():
        resp.headers[k] = v
    return resp


@router.post("/chat", deprecated=True)
async def streaming_chat(request: dict[str, Any]):
    """流式聊天（deprecated → ``POST /chat/streaming``）。"""
    try:
        if not request.get("message"):
            raise HTTPException(status_code=400, detail="消息内容不能为空")

        resp = await optimized_chat_service.chat_streaming(request)
        return _stamp_streaming(resp, "/chat/streaming")

    except Exception as e:
        logger.error(f"流式聊天失败: {e}")
        err_msg = str(e)

        async def error_stream():
            yield f"data: {json.dumps({'error': err_msg, 'type': 'error'})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                **_dep_headers("/chat/streaming"),
            },
        )


@router.post("/chat/with-metadata", deprecated=True)
async def streaming_chat_with_metadata(request: dict[str, Any]):
    """带元数据流式聊天（deprecated → ``POST /chat/streaming``）。"""
    try:
        user_input = request.get("message", "")
        request.get("session_id", "default")
        request.get("user_id", "anonymous")
        metadata = request.get("metadata", {})

        request_time = datetime.now().isoformat()

        async def enhanced_stream():
            yield f"data: {json.dumps({'type': 'start', 'timestamp': request_time})}\n\n"
            yield f"data: {json.dumps({'type': 'processing', 'message': '正在分析您的消息...'})}\n\n"

            processing_result = await optimized_chat_service._parallel_process_input(
                user_input
            )

            yield f"data: {json.dumps({'type': 'analysis', 'processing_time': processing_result.get('processing_time')})}\n\n"

            prompt = await optimized_chat_service._build_optimized_prompt(
                user_input, processing_result
            )

            yield f"data: {json.dumps({'type': 'generating', 'message': '正在生成回复...'})}\n\n"

            response_text = ""
            async for chunk in optimized_chat_service.performance_optimizer.stream_response(
                prompt, optimized_chat_service.llm_client
            ):
                if chunk.startswith("data: "):
                    token = chunk[6:].strip()
                    if token and token != "[DONE]":
                        response_text += token
                        yield f"data: {json.dumps({'type': 'token', 'content': token, 'position': len(response_text)})}\n\n"

            yield f"data: {json.dumps({'type': 'complete', 'full_response': response_text, 'metadata': metadata})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            enhanced_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Content-Type-Options": "nosniff",
                **_dep_headers("/chat/streaming"),
            },
        )

    except Exception as e:
        logger.error(f"带元数据的流式聊天失败: {e}")
        err_msg = str(e)

        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': err_msg})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers=_dep_headers("/chat/streaming"),
        )


@router.get("/status", deprecated=True)
async def get_streaming_status():
    """流式状态（deprecated → ``GET /performance/streams/active``）。"""
    try:
        from backend.services.performance_optimizer import stream_handler

        active_streams = stream_handler.get_active_streams()

        body = {
            "status": "active",
            "active_streams": len(active_streams),
            "streams": active_streams,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"获取流式状态失败: {e}")
        body = {
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat(),
        }
    return JSONResponse(
        content=body,
        headers=_dep_headers("/performance/streams/active"),
    )


@router.post("/test", deprecated=True)
async def test_streaming():
    """测试流（deprecated → ``GET /performance/benchmark``）。"""

    async def test_stream():
        messages = [
            "正在连接...",
            "分析您的请求...",
            "检索相关信息...",
            "生成回复中...",
            "完成！",
        ]

        for i, message in enumerate(messages):
            yield f"data: {json.dumps({'step': i + 1, 'total': len(messages), 'message': message})}\n\n"
            await asyncio.sleep(0.5)

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        test_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            **_dep_headers("/performance/benchmark"),
        },
    )


@router.websocket("/ws")
async def websocket_chat(websocket):
    """WebSocket 流式聊天（旁路保留；主入口请用 SSE ``/chat/streaming``）。"""
    try:
        await websocket.accept()

        while True:
            data = await websocket.receive_text()
            request = json.loads(data)

            user_input = request.get("message", "")
            if not user_input:
                await websocket.send_text(json.dumps({"error": "消息不能为空"}))
                continue

            await websocket.send_text(
                json.dumps(
                    {
                        "type": "start",
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            )

            try:
                processing_result = await optimized_chat_service._parallel_process_input(
                    user_input
                )

                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "analysis",
                            "processing_time": processing_result.get("processing_time"),
                        }
                    )
                )

                prompt = await optimized_chat_service._build_optimized_prompt(
                    user_input, processing_result
                )
                response = await optimized_chat_service._generate_response_optimized(
                    prompt
                )

                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "response",
                            "content": response,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                )

            except Exception as e:
                logger.error(f"WebSocket聊天处理失败: {e}")
                await websocket.send_text(
                    json.dumps({"type": "error", "message": str(e)})
                )

    except Exception as e:
        logger.error(f"WebSocket连接失败: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/", deprecated=True)
async def streaming_info():
    """流式服务信息（deprecated → ``/chat/streaming``）。"""
    return JSONResponse(
        content={
            "service": "流式聊天服务",
            "version": "1.0.0",
            "deprecated": True,
            "successor": "/chat/streaming",
            "features": [
                "Server-Sent Events (SSE)",
                "WebSocket支持",
                "实时元数据",
                "性能优化",
                "错误处理",
            ],
            "endpoints": {
                "POST /streaming/chat": "基础流式聊天",
                "POST /streaming/chat/with-metadata": "带元数据的流式聊天",
                "GET /streaming/status": "流式服务状态",
                "POST /streaming/test": "测试流式响应",
                "WS /streaming/ws": "WebSocket聊天",
            },
            "timestamp": datetime.now().isoformat(),
        },
        headers=_dep_headers("/chat/streaming"),
    )
