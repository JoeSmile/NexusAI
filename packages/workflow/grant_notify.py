"""E3.3 — grant.expiring 通知扫描。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def scan_expiring_grants(
    *,
    within_days: int = 7,
    now: datetime | None = None,
    limit: int = 100,
) -> dict[str, int]:
    """到期前 7 天提醒；已 auto_renew 成功的不推（先续期后通知由 grant_scanner 顺序保证）。"""
    from packages.database.pgvector_session import (
        PermissionRequest,
        Workflow,
        WorkflowGrant,
        get_pg_session,
    )
    from packages.notification.service import notify
    from packages.workflow.grants import normalize_request_policy

    now = now or datetime.utcnow()
    horizon = now + timedelta(days=within_days)
    notified = 0
    skipped = 0
    sf = get_pg_session()
    with sf.Session() as session:
        rows = (
            session.query(WorkflowGrant)
            .filter(
                WorkflowGrant.revoked_at.is_(None),
                WorkflowGrant.expires_at <= horizon,
                WorkflowGrant.expires_at > now,
            )
            .order_by(WorkflowGrant.expires_at.asc())
            .limit(limit)
            .all()
        )
        for grant in rows:
            # 已有 renew:{id} 后继 → 续期成功，不提醒
            successor = (
                session.query(WorkflowGrant)
                .filter(
                    WorkflowGrant.origin == f"renew:{grant.id}",
                    WorkflowGrant.tenant_id == grant.tenant_id,
                )
                .one_or_none()
            )
            if successor is not None:
                skipped += 1
                continue
            # I4：仅有 renew 后继才跳过；auto_renew 但未续上 → 仍提醒
            req = (
                session.query(PermissionRequest)
                .filter(PermissionRequest.id == grant.request_id)
                .one_or_none()
            )
            marker = "grant_expiring_notified"
            if req and marker in (req.review_reason or ""):
                skipped += 1
                continue
            wf = (
                session.query(Workflow)
                .filter(
                    Workflow.id == grant.workflow_id,
                    Workflow.tenant_id == grant.tenant_id,
                )
                .one_or_none()
            )
            policy = normalize_request_policy(
                dict(wf.request_policy) if wf and wf.request_policy else None
            )
            cap0 = (grant.caps or [{}])[0] if isinstance(grant.caps, list) else {}
            capability_id = str(
                (cap0.get("capability_id") if isinstance(cap0, dict) else None)
                or (req.capability_id if req else "")
                or ""
            )
            payload = {
                "grant_id": grant.id,
                "workflow_id": grant.workflow_id,
                "capability_id": capability_id,
                "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
                "auto_renew": bool(policy.get("auto_renew")),
            }
            targets = {grant.applicant_user_id}
            if req and req.reviewed_by:
                targets.add(req.reviewed_by)
            for uid in targets:
                if not uid or uid.startswith("system:"):
                    continue
                try:
                    notify(grant.tenant_id, uid, "grant.expiring", payload)
                    notified += 1
                except Exception:
                    logger.debug("grant.expiring notify failed", exc_info=True)
            if req is not None:
                reason = (req.review_reason or "").strip()
                req.review_reason = f"{reason};{marker}" if reason else marker
                req.updated_at = now
        session.commit()
    return {"notified": notified, "skipped": skipped}
