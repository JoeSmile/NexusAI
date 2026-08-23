"""Capability admin persistence — DB upsert + in-memory registry (Task 67)."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from backend.core.capability.models import CapabilitySpec, CapabilityStatus
from backend.core.capability.registry import get_capability_registry

logger = logging.getLogger(__name__)


def _upsert_db_row(spec: CapabilitySpec) -> None:
    from backend.database.pgvector_session import Capability, get_pg_session

    pg = get_pg_session()
    with pg.get_session() as session:
        row = session.query(Capability).filter(Capability.id == spec.id).first()
        if row is None:
            row = Capability(
                id=spec.id,
                tenant_id=spec.tenant_id or "*",
                name=spec.name,
                kind=spec.kind.value,
                provider=spec.provider.value,
                spec=dict(spec.spec or {}),
                status=spec.status.value,
                cost_model=dict(spec.cost_model or {}),
                permission=spec.permission or "",
                param_spec=dict(spec.param_spec) if spec.param_spec else None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(row)
        else:
            row.tenant_id = spec.tenant_id or "*"
            row.name = spec.name
            row.kind = spec.kind.value
            row.provider = spec.provider.value
            row.spec = dict(spec.spec or {})
            row.status = spec.status.value
            row.cost_model = dict(spec.cost_model or {})
            row.permission = spec.permission or ""
            row.param_spec = dict(spec.param_spec) if spec.param_spec else None
            row.updated_at = datetime.utcnow()
        session.commit()


def persist_capability_spec(spec: CapabilitySpec) -> CapabilitySpec:
    """Write capability to DB (best-effort) and refresh in-memory registry."""
    try:
        _upsert_db_row(spec)
    except Exception as exc:
        logger.warning("capability DB persist skipped for %s: %s", spec.id, exc)
    get_capability_registry().register(spec)
    return spec


def update_capability_status(capability_id: str, status: CapabilityStatus) -> CapabilitySpec:
    reg = get_capability_registry()
    spec = reg.get(capability_id, require_enabled=False)
    updated = replace(spec, status=status)
    return persist_capability_spec(updated)


def update_capability_spec_body(
    capability_id: str,
    *,
    spec_patch: dict,
) -> CapabilitySpec:
    reg = get_capability_registry()
    spec = reg.get(capability_id, require_enabled=False)
    nested = dict(spec.spec or {})
    nested.update(spec_patch)
    updated = replace(spec, spec=nested)
    return persist_capability_spec(updated)
