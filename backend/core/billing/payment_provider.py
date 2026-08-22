"""Payment provider abstraction (Task 55 slice 2)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy.orm import Session

from backend.core.billing.wallet import recharge_wallet_in_session


@dataclass(frozen=True)
class RechargeRequest:
    tenant_id: str
    amount: Decimal
    reference_no: str
    operator: str
    method: str = "manual"


@dataclass(frozen=True)
class RechargeResult:
    tenant_id: str
    amount: float
    balance_after: float
    reference_no: str
    method: str


class PaymentProvider(Protocol):
    def recharge(self, session: Session, request: RechargeRequest) -> RechargeResult:
        """Apply a recharge inside an open DB session."""


class ManualPaymentProvider:
    """Phase 1 — admin confirms bank transfer, then credits wallet."""

    def recharge(self, session: Session, request: RechargeRequest) -> RechargeResult:
        balance_after = recharge_wallet_in_session(
            session,
            tenant_id=request.tenant_id,
            amount=request.amount,
            reference_no=request.reference_no,
            operator=request.operator,
            method=request.method,
            tx_type="recharge",
        )
        return RechargeResult(
            tenant_id=request.tenant_id,
            amount=float(request.amount),
            balance_after=balance_after,
            reference_no=request.reference_no,
            method=request.method,
        )


def get_payment_provider(method: str = "manual") -> PaymentProvider:
    if method in ("manual", "bank"):
        return ManualPaymentProvider()
    raise ValueError(f"unsupported_payment_method:{method}")
