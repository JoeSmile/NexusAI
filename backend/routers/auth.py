"""账号认证路由 — 注册 / 登录 (Task 38 → Wave A JWT)。

无全局 auth Depends:这两个端点自身校验用户名密码。
登录/注册成功后下发 JWT access_token（禁止再建 api_keys）。
失败计数走 Redis(降级到进程内 dict),5 次/5 分钟触发 429。
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.core.audit import log_audit
from backend.core.auth.jwt_session import issue_access_token, jwt_ttl_seconds
from backend.core.auth.password import hash_password, verify_password
from backend.core.redis_tools import get_sync_redis
from backend.database.pgvector_session import get_pg_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── 常量 ────────────────────────────────────────
_REGISTER_ALLOWED_ENVS = {"dev", "test", "demo"}
_DEFAULT_TENANT = "acme"
_ALLOWED_ROLES = {"user", "tenant_admin", "auditor", "super_admin"}
_FAIL_WINDOW_SEC = 300  # 5 分钟
_FAIL_MAX = 5

# 进程内降级计数器(username -> [fail_count, first_fail_monotonic])
_fail_fallback: dict[str, list[float]] = {}


# ── Schema ─────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None
    role: str = "user"


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    tenant_id: str
    user_id: str


# ── Helpers ────────────────────────────────────
def _normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _app_env() -> str:
    # 未设置时按 prod 处理(注册闸门 fail-closed);显式 APP_ENV=dev|test|demo 才开放注册。
    raw = (os.getenv("APP_ENV") or "").strip().lower()
    return raw or "prod"


def _fail_key(username: str, *, kind: str = "fail") -> str:
    """kind=fail → 登录失败;kind=reg → 注册尝试(防爆破/枚举)。"""
    return f"auth:{kind}:{username}"


def _fail_incr(username: str, *, kind: str = "fail") -> int:
    """失败/尝试计数 +1,返回当前窗口内累计次数。Redis 优先,失败降级进程内 dict。"""
    r = get_sync_redis(decode_responses=True)
    key = _fail_key(username, kind=kind)
    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, _FAIL_WINDOW_SEC)
            count_raw, _ = pipe.execute()
            return int(count_raw)
        except Exception as e:
            logger.warning("auth fail-counter redis error, fallback: %s", e)
    # 降级:进程内 dict(用完整 redis key 做本地槽位,避免 login/reg 互相污染)
    now = time.monotonic()
    rec = _fail_fallback.get(key)
    if rec is None or (now - rec[1]) > _FAIL_WINDOW_SEC:
        rec = [0.0, now]
    rec[0] += 1
    _fail_fallback[key] = rec
    return int(rec[0])


def _fail_count(username: str, *, kind: str = "fail") -> int:
    r = get_sync_redis(decode_responses=True)
    key = _fail_key(username, kind=kind)
    if r is not None:
        try:
            raw = r.get(key)
            return int(raw) if raw else 0
        except Exception:
            return 0
    rec = _fail_fallback.get(key)
    if rec is None:
        return 0
    now = time.monotonic()
    if (now - rec[1]) > _FAIL_WINDOW_SEC:
        return 0
    return int(rec[0])


def _fail_clear(username: str, *, kind: str = "fail") -> None:
    r = get_sync_redis(decode_responses=True)
    key = _fail_key(username, kind=kind)
    if r is not None:
        try:
            r.delete(key)
            return
        except Exception:
            pass
    _fail_fallback.pop(key, None)


def _token_response(*, user_id: str, tenant_id: str, role: str) -> AuthResponse:
    token = issue_access_token(sub=user_id, tid=tenant_id, role=role)
    return AuthResponse(
        access_token=token,
        token_type="bearer",
        expires_in=jwt_ttl_seconds(),
        role=role,
        tenant_id=tenant_id,
        user_id=user_id,
    )


# ── Routes ─────────────────────────────────────
@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest, background_tasks: BackgroundTasks):
    """注册新账号 → 创建 users 行，返回 JWT（禁止 INSERT api_keys）。"""
    if _app_env() not in _REGISTER_ALLOWED_ENVS:
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_010", "message": "register_disabled_in_prod"},
        )

    username = _normalize_username(req.username)
    if not username:
        raise HTTPException(
            status_code=422,
            detail={"code": "AUTH_011", "message": "username_required"},
        )
    if _fail_count(username, kind="reg") >= _FAIL_MAX:
        raise HTTPException(
            status_code=429,
            detail={"code": "AUTH_016", "message": "too_many_attempts"},
        )
    if len(req.password) < 8:
        raise HTTPException(
            status_code=422,
            detail={"code": "AUTH_012", "message": "password_too_short"},
        )
    if req.role not in _ALLOWED_ROLES:
        raise HTTPException(
            status_code=422,
            detail={"code": "AUTH_013", "message": "invalid_role"},
        )

    display_name = (req.display_name or username).strip() or username
    password_hash = hash_password(req.password)
    tenant_id = _DEFAULT_TENANT
    user_id = username

    session_factory = get_pg_session()
    try:
        with session_factory.Session() as session:
            existing = session.execute(
                text("SELECT id FROM users WHERE username = :u LIMIT 1"),
                {"u": username},
            ).fetchone()
            if existing is not None:
                count = _fail_incr(username, kind="reg")
                if count >= _FAIL_MAX:
                    raise HTTPException(
                        status_code=429,
                        detail={"code": "AUTH_016", "message": "too_many_attempts"},
                    )
                raise HTTPException(
                    status_code=409,
                    detail={"code": "AUTH_014", "message": "username_taken"},
                )

            # G1/G8：席位硬限（拍板 3B 上线闸；I-2 专用异常）
            try:
                from backend.core.workflow.subscription import (
                    SeatLimitExceeded,
                    assert_seat_available,
                )

                assert_seat_available(session, tenant_id=tenant_id, adding=1)
            except SeatLimitExceeded:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "SEAT_LIMIT",
                        "message": "seat_limit_exceeded_contact_admin",
                    },
                ) from None

            session.execute(
                text(
                    """
                    INSERT INTO users
                        (user_id, username, password_hash, display_name,
                         tenant_id, role, is_active, created_at, updated_at)
                    VALUES (:uid, :uname, :ph, :dn, :tid, :role, true, now(), now())
                    """
                ),
                {
                    "uid": user_id,
                    "uname": username,
                    "ph": password_hash,
                    "dn": display_name,
                    "tid": tenant_id,
                    "role": req.role,
                },
            )
            session.commit()
    except HTTPException:
        raise
    except IntegrityError as e:
        count = _fail_incr(username, kind="reg")
        if count >= _FAIL_MAX:
            raise HTTPException(
                status_code=429,
                detail={"code": "AUTH_016", "message": "too_many_attempts"},
            ) from e
        raise HTTPException(
            status_code=409,
            detail={"code": "AUTH_014", "message": "username_taken"},
        ) from e
    except Exception as e:
        logger.exception("register failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "AUTH_015", "message": "register_failed"},
        ) from e

    _fail_clear(username, kind="reg")

    log_audit(
        background_tasks,
        tenant_id=tenant_id,
        user_id=user_id,
        action="auth.register",
        trace_id="",
        input_text=username,
        output_text="",
        credential_kind="human_session",
    )

    return _token_response(user_id=user_id, tenant_id=tenant_id, role=req.role)


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, background_tasks: BackgroundTasks):
    """账号密码登录 → 校验 bcrypt，返回 JWT（禁止 INSERT/轮换 api_keys）。"""
    username = _normalize_username(req.username)
    if not username:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_001", "message": "invalid_credentials"},
        )

    if _fail_count(username) >= _FAIL_MAX:
        raise HTTPException(
            status_code=429,
            detail={"code": "AUTH_016", "message": "too_many_attempts"},
        )

    session_factory = get_pg_session()
    try:
        with session_factory.Session() as session:
            row = session.execute(
                text(
                    """
                    SELECT user_id, username, password_hash, tenant_id, role, is_active
                    FROM users WHERE username = :u LIMIT 1
                    """
                ),
                {"u": username},
            ).fetchone()
    except Exception as e:
        logger.exception("login lookup failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "AUTH_017", "message": "login_failed"},
        ) from e

    invalid = (
        row is None
        or not row.is_active
        or not verify_password(req.password, row.password_hash or "")
    )
    if invalid:
        count = _fail_incr(username)
        if count >= _FAIL_MAX:
            raise HTTPException(
                status_code=429,
                detail={"code": "AUTH_016", "message": "too_many_attempts"},
            )
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_001", "message": "invalid_credentials"},
        )

    user_id = row.user_id
    tenant_id = row.tenant_id or _DEFAULT_TENANT
    role = row.role or "user"

    _fail_clear(username)

    log_audit(
        background_tasks,
        tenant_id=tenant_id,
        user_id=user_id,
        action="auth.login",
        trace_id="",
        input_text=username,
        output_text="",
        credential_kind="human_session",
    )

    return _token_response(user_id=user_id, tenant_id=tenant_id, role=role)
