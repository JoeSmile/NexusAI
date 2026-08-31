"""Session attachment readiness — real attachments table (Task 76.3)."""

from __future__ import annotations


def session_has_ready_attachments(
    tenant_id: str,
    user_id: str,
    session_id: str,
) -> bool:
    """Unexpired status=ready attachments on this session."""
    del user_id
    from packages.attachments.notice import row_is_live
    from packages.attachments.store import get_attachment_store

    try:
        rows = get_attachment_store().list_session(
            tenant_id=tenant_id, session_id=session_id
        )
    except Exception:
        return False
    return any(r.get("status") == "ready" and row_is_live(r) for r in rows)
