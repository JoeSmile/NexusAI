"""Notification service — fail-soft multi-channel dispatch (Task 44.2)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from packages.audit import write_audit_sync
from packages.database.pgvector_session import ApiKey, Notification, get_pg_session
from packages.notification.channels import (
    ensure_default_providers,
    list_available_providers,
)

logger = logging.getLogger(__name__)

# 引用型 payload 允许的键（禁敏感正文）
_ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "run_id",
        "node_id",
        "request_id",
        "workflow_id",
        "grant_id",
        "org_unit_id",
        "capability_id",
        "conversation_id",
        "platform",
        "status",
        "error_code",
        "summary",
        # E3.3 / E3.3b
        "expires_at",
        "plan",
        "auto_renew",
    }
)


def refs_only(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload or {}
    return {k: v for k, v in raw.items() if k in _ALLOWED_PAYLOAD_KEYS and v is not None}


def _audit_notify(
    *,
    tenant_id: str,
    user_id: str,
    action: str,
    payload: dict[str, Any],
    error: str | None = None,
) -> None:
    try:
        write_audit_sync(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "action": action,
                "trace_id": str(payload.get("run_id") or ""),
                "input_text": "",
                "output_text": (error or action)[:200],
                "model": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0.0,
                "latency_ms": 0.0,
                "error_code": "notify_failed" if error else None,
                "ip_address": "",
                "user_agent": "",
                "credential_kind": None,
                "key_id": None,
                "run_id": payload.get("run_id"),
                "node_id": payload.get("node_id"),
                "created_at": datetime.utcnow(),
            }
        )
    except Exception:
        logger.debug("notify audit failed", exc_info=True)


def notify(
    tenant_id: str,
    user_id: str,
    notif_type: str,
    payload: dict[str, Any] | None = None,
    *,
    session: Session | None = None,
) -> list[str]:
    """按可用 channel 分发；失败静默 + notify_failed 审计。返回写入的 channel 名。"""
    clean = refs_only(payload)
    sent: list[str] = []
    own_session = session is None
    try:
        ensure_default_providers()
        providers = list_available_providers()
        if not providers:
            return sent

        def _dispatch(sess: Session) -> None:
            for provider in providers:
                try:
                    if not provider.available():
                        continue
                    provider.send(
                        sess,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        type=notif_type,
                        payload=clean,
                    )
                    sent.append(provider.name)
                except Exception as exc:
                    logger.debug(
                        "notify channel %s failed", provider.name, exc_info=True
                    )
                    _audit_notify(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        action="notify_failed",
                        payload=clean,
                        error=f"{provider.name}:{type(exc).__name__}",
                    )
            if own_session:
                sess.commit()
            if sent:
                _audit_notify(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action="notify.sent",
                    payload=clean,
                )

        if session is not None:
            _dispatch(session)
        else:
            sf = get_pg_session()
            with sf.Session() as sess:
                _dispatch(sess)
    except Exception:
        logger.debug("notify failed", exc_info=True)
        _audit_notify(
            tenant_id=tenant_id,
            user_id=user_id,
            action="notify_failed",
            payload=clean,
            error="notify_exception",
        )
    return sent


def notify_many(
    tenant_id: str,
    user_ids: list[str] | tuple[str, ...],
    notif_type: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """对多用户投递；单用户失败不影响其余。返回成功用户数。"""
    n = 0
    seen: set[str] = set()
    for uid in user_ids:
        if not uid or uid in seen:
            continue
        seen.add(uid)
        try:
            if notify(tenant_id, uid, notif_type, payload):
                n += 1
        except Exception:
            logger.debug("notify_many user failed uid=%s", uid, exc_info=True)
    return n


def list_tenant_admin_user_ids(session: Session, tenant_id: str) -> list[str]:
    rows = (
        session.query(ApiKey.user_id)
        .filter(
            ApiKey.tenant_id == tenant_id,
            ApiKey.role == "tenant_admin",
            ApiKey.is_active.is_(True),
        )
        .distinct()
        .all()
    )
    return [str(r[0]) for r in rows if r[0]]


def mark_read(
    *,
    tenant_id: str,
    user_id: str,
    notification_id: str,
) -> bool:
    sf = get_pg_session()
    with sf.Session() as session:
        row = (
            session.query(Notification)
            .filter(
                Notification.id == notification_id,
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
            )
            .one_or_none()
        )
        if row is None:
            return False
        if row.read_at is None:
            row.read_at = datetime.utcnow()
            session.commit()
        return True


def unread_count(*, tenant_id: str, user_id: str) -> int:
    sf = get_pg_session()
    with sf.Session() as session:
        return (
            session.query(Notification)
            .filter(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .count()
        )


def list_inbox(
    *,
    tenant_id: str,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    sf = get_pg_session()
    with sf.Session() as session:
        rows = (
            session.query(Notification)
            .filter(
                Notification.tenant_id == tenant_id,
                Notification.user_id == user_id,
            )
            .order_by(Notification.created_at.desc())
            .offset(max(0, offset))
            .limit(min(200, max(1, limit)))
            .all()
        )
        # detach
        session.expunge_all()
        return list(rows)


def notify_recurring_due_hook(
    tenant_id: str,
    user_ids: list[str],
    payload: dict[str, Any] | None = None,
) -> int:
    """recurring 到期 hook（预留）：本任务只接线类型，不实现推送体业务。"""
    return notify_many(tenant_id, user_ids, "hang.recurring_due", payload or {})


def notify_run_terminal(
    *,
    tenant_id: str,
    user_id: str,
    run_id: str,
    workflow_id: str | None,
    status: str,
    conversation_id: str | None = None,
    platform: str | None = None,
    error_code: str | None = None,
    summary: str | None = None,
) -> list[str]:
    """44.4: run_completed / run_failed → inbox (+ future channel by conversation_id).

    拍板 4A: failed payload 只含 error_code + 固定友好文案；禁止 error_message 明文。
    ``summary`` 参数保留兼容，失败路径忽略（避免异常串渗入）。
    """
    event = "run_completed" if status == "succeeded" else "run_failed"
    payload: dict[str, Any] = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "status": status,
        "conversation_id": conversation_id,
        "platform": platform,
        "error_code": error_code if status != "succeeded" else None,
        "summary": (
            None
            if status == "succeeded"
            else "运行失败，可在工作台查看详情并重试"
        ),
    }
    _ = summary  # discarded on fail path (4A)
    return notify(tenant_id, user_id, event, payload)
