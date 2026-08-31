"""User-visible copy while session attachments are still parsing."""

from __future__ import annotations

from datetime import UTC, datetime

PARSING_USER_MESSAGE = "文件正在解析，请稍后再问。"


def row_is_live(row: dict, *, now: datetime | None = None) -> bool:
    exp = row.get("expired_at")
    if exp is None:
        return True
    if getattr(exp, "tzinfo", None) is None:
        exp = exp.replace(tzinfo=UTC)
    stamp = now or datetime.now(UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return exp > stamp


def _alive(row: dict) -> bool:
    return row_is_live(row)


def parsing_notice_for_session(*, tenant_id: str, session_id: str) -> str | None:
    from packages.attachments.store import get_attachment_store

    try:
        rows = get_attachment_store().list_session(
            tenant_id=tenant_id, session_id=session_id
        )
    except Exception:
        return None
    live = [r for r in rows if _alive(r)]
    has_ready = any(r.get("status") == "ready" for r in live)
    has_parsing = any(r.get("status") == "parsing" for r in live)
    if has_parsing and not has_ready:
        return PARSING_USER_MESSAGE
    return None
