"""E3.3 / E3.3b — payload allowlist + subscription JSON."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from packages.workflow.subscription import get_subscription, set_subscription
from backend.modules.notification.service import refs_only


def test_payload_allowlist_includes_expiry_fields():
    cleaned = refs_only(
        {
            "grant_id": "g1",
            "workflow_id": "w1",
            "capability_id": "kb",
            "expires_at": "2026-09-01T00:00:00",
            "plan": "edu-9800",
            "auto_renew": False,
            "secret": "drop-me",
        }
    )
    assert cleaned["expires_at"] == "2026-09-01T00:00:00"
    assert cleaned["plan"] == "edu-9800"
    assert cleaned["auto_renew"] is False
    assert "secret" not in cleaned


def test_subscription_roundtrip_in_config():
    exp = datetime.utcnow() + timedelta(days=10)
    cfg = set_subscription({}, plan="edu-9800", expires_at=exp)
    sub = get_subscription(cfg)
    assert sub["plan"] == "edu-9800"
    assert "expires_at" in sub


def test_grant_scanner_renew_before_notify_order():
    """I4 / C3：同一扫描器内先续期再通知。"""
    calls: list[str] = []

    def _renew():
        calls.append("renew")
        return {"renewed": 1}

    def _notify():
        calls.append("notify")
        return {"notified": 0}

    def _sub():
        calls.append("sub")
        return {}

    with patch(
        "packages.workflow.grants.scan_grants_for_auto_renew", side_effect=_renew
    ), patch(
        "packages.workflow.grant_notify.scan_expiring_grants", side_effect=_notify
    ), patch(
        "packages.workflow.subscription.scan_subscription_expiring",
        side_effect=_sub,
    ):
        from packages.workflow.grant_scanner import scan_once

        scan_once()
    assert calls[:2] == ["renew", "notify"]
