"""账号认证路由 — 注册 / 登录 (Task 38.01)。

无全局 auth Depends:这两个端点自身校验用户名密码,登录成功后下发 cg_ API Key。
失败计数走 Redis(降级到进程内 dict),5 次/5 分钟触发 429。
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.core.audit import log_audit
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
    api_key: str  # 明文,仅此一次返回
    role: str
    tenant_id: str
    user_id: str


# ── Helpers ────────────────────────────────────
def _normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _app_env() -> str:
    return (os.getenv("APP_ENV") or "dev").strip().lower()


def _fail_key(username: str) -> str:
    return f"auth:fail:{username}"


def _fail_incr(username: str) -> int:
    """失败计数 +1,返回当前窗口内累计次数。Redis 优先,失败降级进程内 dict。"""
    r = get_sync_redis(decode_responses=True)
    key = _fail_key(username)
    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, _FAIL_WINDOW_SEC)
            count_raw, _ = pipe.execute()
            return int(count_raw)
        except Exception as e:
            logger.warning("auth fail-counter redis error, fallback: %s", e)
    # 降级:进程内 dict
    now = time.monotonic()
    rec = _fail_fallback.get(username)
    if rec is None or (now - rec[1]) > _FAIL_WINDOW_SEC:
        rec = [0.0, now]
    rec[0] += 1
    _fail_fallback[username] = rec
    return int(rec[0])


def _fail_count(username: str) -> int:
    r = get_sync_redis(decode_responses=True)
    key = _fail_key(username)
    if r is not None:
        try:
            raw = r.get(key)
            return int(raw) if raw else 0
        except Exception:
            return 0
    rec = _fail_fallback.get(username)
    if rec is None:
        return 0
    now = time.monotonic()
    if (now - rec[1]) > _FAIL_WINDOW_SEC:
        return 0
    return int(rec[0])


def _fail_clear(username: str) -> None:
    r = get_sync_redis(decode_responses=True)
    key = _fail_key(username)
    if r is not None:
        try:
            r.delete(key)
            return
        except Exception:
            pass
    _fail_fallback.pop(username, None)


def _mint_key() -> tuple[str, str, str]:
    """生成 cg_ key:返回 (raw_key, key_hash, key_prefix)。"""
    raw_key = f"cg_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]
    return raw_key, key_hash, key_prefix


def _insert_api_key(
    session,
    *,
    tenant_id: str,
    user_id: str,
    role: str,
    created_by: str,
    description: str = "",
) -> str:
    """插入新 active key;返回明文。"""
    raw_key, key_hash, key_prefix = _mint_key()
    session.execute(
        text(
            """
            INSERT INTO api_keys
                (tenant_id, user_id, key_hash, key_prefix, role,
                 description, created_by, is_active, created_at)
            VALUES (:tid, :uid, :hash, :prefix, :role,
                    :desc, :by, true, now())
            """
        ),
        {
            "tid": tenant_id,
            "uid": user_id,
            "hash": key_hash,
            "prefix": key_prefix,
            "role": role,
            "desc": description,
            "by": created_by,
        },
    )
    return raw_key


def _rotate_user_keys(session, *, tenant_id: str, user_id: str, role: str) -> None:
    """停用该 (tenant, user, role) 槽位下的 active key(轮换)。"""
    session.execute(
        text(
            """
            UPDATE api_keys SET is_active = false, expires_at = now()
            WHERE tenant_id = :tid AND user_id = :uid AND role = :role
                  AND is_active = true
            """
        ),
        {"tid": tenant_id, "uid": user_id, "role": role},
    )


# ── Routes ─────────────────────────────────────
@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest, background_tasks: BackgroundTasks):
    """注册新账号 → 创建 users 行 + api_keys 行,返回明文 key(仅一次)。"""
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
    user_id = username  # seed 兼容:user_id == username

    session_factory = get_pg_session()
    raw_key = ""
    try:
        with session_factory.Session() as session:
            existing = session.execute(
                text("SELECT id FROM users WHERE username = :u LIMIT 1"),
                {"u": username},
            ).fetchone()
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "AUTH_014", "message": "username_taken"},
                )

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
            raw_key = _insert_api_key(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                role=req.role,
                created_by="register",
                description=f"register:{username}",
            )
            session.commit()
    except HTTPException:
        raise
    except IntegrityError as e:
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

    log_audit(
        background_tasks,
        tenant_id=tenant_id,
        user_id=user_id,
        action="auth.register",
        trace_id="",
        input_text=username,
        output_text="",
    )

    return AuthResponse(
        api_key=raw_key, role=req.role, tenant_id=tenant_id, user_id=user_id
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, background_tasks: BackgroundTasks):
    """账号密码登录 → 校验 bcrypt,成功下发新 cg_ key(轮换旧 active key)。"""
    username = _normalize_username(req.username)
    if not username:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_001", "message": "invalid_credentials"},
        )

    # 失败计数预检:已超阈值直接 429
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

    raw_key = ""
    try:
        with session_factory.Session() as session:
            _rotate_user_keys(
                session, tenant_id=tenant_id, user_id=user_id, role=role
            )
            raw_key = _insert_api_key(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                role=role,
                created_by="login",
                description=f"login:{username}@{datetime.utcnow().isoformat()}",
            )
            session.commit()
    except Exception as e:
        logger.exception("login key issue failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "AUTH_017", "message": "login_failed"},
        ) from e

    _fail_clear(username)

    log_audit(
        background_tasks,
        tenant_id=tenant_id,
        user_id=user_id,
        action="auth.login",
        trace_id="",
        input_text=username,
        output_text="",
    )

    return AuthResponse(
        api_key=raw_key, role=role, tenant_id=tenant_id, user_id=user_id
    )
