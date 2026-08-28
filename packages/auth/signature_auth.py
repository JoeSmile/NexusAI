"""
HMAC-SHA256 请求签名 + 防重放中间件。

签名算法:
  string_to_sign = HTTP_METHOD + "\\n"
                 + PATH + "\\n"
                 + BODY_SHA256 (hex) + "\\n"
                 + TIMESTAMP + "\\n"
                 + NONCE
  signature = hmac_sha256(secret, string_to_sign)

Header 约定:
  X-CG-Access-Key-Id    — api_keys 表的 access_key_id
  X-CG-Signature        — hex(hmac_sha256)
  X-CG-Timestamp        — Unix 毫秒时间戳
  X-CG-Nonce            — UUID v4（窗口期内不可重复）

防重放窗口: ±5 分钟
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from collections import OrderedDict

from fastapi import HTTPException, Request
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.database.pgvector_session import get_pg_session


class NonceCache:
    """非持久化 nonce 去重 — TTL 缓存"""

    MAX_SIZE = 10000
    TTL_SEC = 300  # 5 分钟

    def __init__(self) -> None:
        self._cache: OrderedDict[str, int] = OrderedDict()

    def has(self, nonce: str) -> bool:
        self._evict()
        return nonce in self._cache

    def add(self, nonce: str) -> None:
        self._cache[nonce] = int(time.time())
        if len(self._cache) > self.MAX_SIZE:
            self._cache.popitem(last=False)

    def _evict(self) -> None:
        now = int(time.time())
        stale = [k for k, v in self._cache.items() if now - v > self.TTL_SEC]
        for k in stale:
            del self._cache[k]


NONCE_CACHE = NonceCache()


async def verify_request_signature(request: Request) -> bytes | None:
    """验证请求签名 — 在 auth_check 前执行。返回已读 body（若读过）。"""
    if request.method.upper() == "OPTIONS":
        return None

    key_id = request.headers.get("X-CG-Access-Key-Id")
    if not key_id:
        return None  # 向后兼容: 无签名头走现有 X-API-Key 认证

    signature = request.headers.get("X-CG-Signature")
    timestamp_str = request.headers.get("X-CG-Timestamp")
    nonce = request.headers.get("X-CG-Nonce")

    if signature is None or timestamp_str is None or nonce is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "AUTH_005", "message": "missing_signature_headers"},
        )

    try:
        ts_ms = int(timestamp_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "AUTH_006", "message": "invalid_timestamp"},
        ) from exc

    now_ms = int(time.time() * 1000)
    if abs(now_ms - ts_ms) > 300_000:  # ±5 分钟
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_007", "message": "signature_expired_or_future"},
        )

    nonce_key = f"{key_id}:{nonce}"
    if NONCE_CACHE.has(nonce_key):
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_008", "message": "nonce_reused"},
        )

    secret = await _get_key_secret(key_id)
    if not secret:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_009", "message": "invalid_access_key"},
        )

    # request.body() 会消费流 — 读后由中间件重新注入 receive
    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    string_to_sign = (
        f"{request.method}\n{request.url.path}\n{body_hash}\n{timestamp_str}\n{nonce}"
    )
    expected = hmac.new(
        secret.encode(), string_to_sign.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_010", "message": "signature_mismatch"},
        )

    NONCE_CACHE.add(nonce_key)
    request.state.signature_verified = True
    request.state.signer_key_id = key_id
    return body


async def _get_key_secret(key_id: str) -> str | None:
    """从 api_keys 表查 access_key_secret"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            SELECT access_key_secret FROM api_keys
            WHERE access_key_id = :kid AND is_active = true
        """)
        row = session.execute(sql, {"kid": key_id}).fetchone()
    if row and row.access_key_secret:
        return row.access_key_secret
    return None


class SignatureMiddleware(BaseHTTPMiddleware):
    """全局签名校验中间件 — 注册到 FastAPI app"""

    async def dispatch(self, request, call_next):
        try:
            body = await verify_request_signature(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
            )

        if body is not None:
            # BaseHTTPMiddleware 下重新注入 body，避免下游读不到
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(request.scope, receive)

        return await call_next(request)


def sign_request(
    method: str,
    path: str,
    body: bytes,
    secret: str,
    access_key_id: str,
) -> dict[str, str]:
    """生成签名头（客户端使用）。access_key_id 必须与 api_keys.access_key_id 一致。"""
    if not access_key_id:
        raise ValueError("access_key_id is required")
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    body_hash = hashlib.sha256(body).hexdigest()
    string_to_sign = f"{method}\n{path}\n{body_hash}\n{ts}\n{nonce}"
    sig = hmac.new(
        secret.encode(), string_to_sign.encode(), hashlib.sha256
    ).hexdigest()
    return {
        "X-CG-Access-Key-Id": access_key_id,
        "X-CG-Signature": sig,
        "X-CG-Timestamp": ts,
        "X-CG-Nonce": nonce,
    }
