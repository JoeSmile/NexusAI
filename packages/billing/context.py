"""Billing request context — user/trace/key for usage_records."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass
class BillingContext:
    user_id: str | None = None
    trace_id: str | None = None
    credential_kind: str = "company"
    key_id: str | None = None
    provider: str | None = None
    idempotency_suffix: str = "llm"
    modality: str | None = None
    image_hash: str | None = None


_billing: ContextVar[BillingContext | None] = ContextVar("billing_context", default=None)


def bind_billing_context(
    *,
    user_id: str | None = None,
    trace_id: str | None = None,
    credential_kind: str | None = None,
    key_id: str | None = None,
    provider: str | None = None,
    idempotency_suffix: str | None = None,
    modality: str | None = None,
    image_hash: str | None = None,
) -> BillingContext:
    current = get_billing_context()
    merged = BillingContext(
        user_id=user_id if user_id is not None else current.user_id,
        trace_id=trace_id if trace_id is not None else current.trace_id,
        credential_kind=credential_kind or current.credential_kind,
        key_id=key_id if key_id is not None else current.key_id,
        provider=provider if provider is not None else current.provider,
        idempotency_suffix=idempotency_suffix or current.idempotency_suffix,
        modality=modality if modality is not None else current.modality,
        image_hash=image_hash if image_hash is not None else current.image_hash,
    )
    _billing.set(merged)
    return merged


def bind_billing_from_pipeline_state(state: dict[str, Any]) -> BillingContext:
    suffix = "stream" if state.get("stream_mode") else "llm"
    return bind_billing_context(
        user_id=str(state.get("user_id") or ""),
        trace_id=state.get("trace_id"),
        credential_kind="company",
        key_id=state.get("llm_key_id"),
        provider=state.get("llm_key_provider"),
        idempotency_suffix=suffix,
    )


def get_billing_context() -> BillingContext:
    return _billing.get() or BillingContext()


def clear_billing_context() -> None:
    _billing.set(None)
