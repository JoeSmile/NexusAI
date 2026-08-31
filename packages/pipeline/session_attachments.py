"""Session attachment readiness — Task 76.0 stub; slice 1 replaces with a real SELECT."""

from __future__ import annotations


def session_has_ready_attachments(
    tenant_id: str,
    user_id: str,
    session_id: str,
) -> bool:
    """Unexpired status=ready attachments on this session.

    Slice 0 default: False. Tests monkeypatch. Slice 3 wires the attachments table.
    """
    del tenant_id, user_id, session_id
    return False
