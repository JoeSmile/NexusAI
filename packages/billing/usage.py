"""Metered usage_records writer (append-only, billing-grade)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.core.audit_context import get_audit_lineage
from backend.database.pgvector_session import get_pg_session
from packages.billing.context import get_billing_context
from packages.billing.wallet import (
    InsufficientBalanceError,
    deduct_balance_in_session,
    is_wallet_billing_enabled,
)

logger = logging.getLogger(__name__)

_INSERT_SQL = text(
    """
    INSERT INTO usage_records (
        tenant_id, user_id, trace_id, credential_kind, key_id,
        model, provider, input_tokens, output_tokens, cost, currency,
        billing_month, idempotency_key, modality, image_hash, created_at
    ) VALUES (
        :tenant_id, :user_id, :trace_id, :credential_kind, :key_id,
        :model, :provider, :input_tokens, :output_tokens, :cost, :currency,
        :billing_month, :idempotency_key, :modality, :image_hash, :created_at
    )
    """
)


def make_idempotency_key(
    *,
    trace_id: str | None,
    model: str,
    suffix: str,
) -> str:
    lineage = get_audit_lineage()
    part = lineage.tool_use_id or suffix
    base = f"{trace_id or 'no-trace'}:{model}:{part}"
    return base[:128]


def _resolve_provider(model: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        from backend.core.model_registry import get_model

        spec = get_model(model)
        if spec is not None and spec.provider:
            return str(spec.provider)
    except Exception:
        pass
    return "default"


def record_metered_usage(
    *,
    tenant_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost: float,
    user_id: str | None = None,
    trace_id: str | None = None,
    credential_kind: str | None = None,
    key_id: str | None = None,
    provider: str | None = None,
    currency: str = "CNY",
    idempotency_key: str | None = None,
    modality: str | None = None,
    image_hash: str | None = None,
) -> bool:
    """Persist one usage row. Returns False when skipped or duplicate."""
    ctx = get_billing_context()
    uid = (user_id or ctx.user_id or "").strip()
    if not uid:
        return False

    tid = trace_id if trace_id is not None else ctx.trace_id
    kind = credential_kind or ctx.credential_kind or "company"
    kid = key_id if key_id is not None else ctx.key_id
    prov = _resolve_provider(model, provider or ctx.provider)
    ikey = idempotency_key or make_idempotency_key(
        trace_id=tid,
        model=model,
        suffix=ctx.idempotency_suffix,
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    billing_month = now.strftime("%Y-%m")

    params = {
        "tenant_id": tenant_id,
        "user_id": uid,
        "trace_id": tid,
        "credential_kind": kind,
        "key_id": kid,
        "model": model,
        "provider": prov,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cost": Decimal(str(round(float(cost), 6))),
        "currency": currency,
        "billing_month": billing_month,
        "idempotency_key": ikey,
        "modality": modality or ctx.modality or "text",
        "image_hash": image_hash or ctx.image_hash,
        "created_at": now,
    }

    session_factory = get_pg_session()
    try:
        with session_factory.Session() as session:
            session.execute(_INSERT_SQL, params)
            kind = params["credential_kind"]
            if is_wallet_billing_enabled() and kind != "byok" and float(cost) > 0:
                deduct_balance_in_session(
                    session,
                    tenant_id=tenant_id,
                    amount=float(cost),
                    reference_no=ikey,
                    operator=uid,
                )
            session.commit()
        return True
    except InsufficientBalanceError:
        raise
    except IntegrityError:
        logger.debug("usage_records duplicate idempotency_key=%s", ikey)
        return False
    except Exception:
        logger.exception("usage_records insert failed tenant=%s model=%s", tenant_id, model)
        return False
