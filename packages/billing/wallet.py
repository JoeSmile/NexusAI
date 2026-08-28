"""Prepaid wallet — balance, recharge, atomic deduction (Task 55 slice 2)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.core.errors import ErrorCode
from backend.database.pgvector_session import get_pg_session

_INSUFFICIENT = ErrorCode.INSUFFICIENT_BALANCE.value

_SELECT_WALLET_FOR_UPDATE = text(
    """
    SELECT balance, version, currency
    FROM wallets
    WHERE tenant_id = :tid
    FOR UPDATE
    """
)

_INSERT_WALLET = text(
    """
    INSERT INTO wallets (tenant_id, balance, currency, version, updated_at)
    VALUES (:tid, 0, :currency, 0, :updated_at)
    ON CONFLICT (tenant_id) DO NOTHING
    """
)

_UPDATE_WALLET = text(
    """
    UPDATE wallets
    SET balance = :balance,
        version = version + 1,
        updated_at = :updated_at
    WHERE tenant_id = :tid AND version = :version
    """
)

_INSERT_TX = text(
    """
    INSERT INTO wallet_transactions (
        tenant_id, type, amount, balance_after, method, reference_no, operator, created_at
    ) VALUES (
        :tenant_id, :type, :amount, :balance_after, :method, :reference_no, :operator, :created_at
    )
    """
)


class InsufficientBalanceError(Exception):
    """Raised when wallet balance cannot cover a debit."""

    code: str = _INSUFFICIENT

    def __init__(self, tenant_id: str, needed: Decimal, available: Decimal) -> None:
        self.tenant_id = tenant_id
        self.needed = needed
        self.available = available
        super().__init__(
            f"insufficient_balance tenant={tenant_id} needed={needed} available={available}"
        )


def is_wallet_billing_enabled() -> bool:
    return os.getenv("BILLING_WALLET_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _decimal(value: float | Decimal) -> Decimal:
    return Decimal(str(round(float(value), 4)))


def _lock_wallet_row(session: Session, tenant_id: str) -> object:
    row = session.execute(_SELECT_WALLET_FOR_UPDATE, {"tid": tenant_id}).fetchone()
    if row is not None:
        return row
    now = datetime.now(UTC).replace(tzinfo=None)
    session.execute(
        _INSERT_WALLET,
        {"tid": tenant_id, "currency": "CNY", "updated_at": now},
    )
    return session.execute(_SELECT_WALLET_FOR_UPDATE, {"tid": tenant_id}).fetchone()


def get_balance_sync(tenant_id: str) -> float:
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        row = session.execute(
            text("SELECT balance FROM wallets WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).fetchone()
    if row is None:
        return 0.0
    return float(row.balance or 0.0)


async def check_wallet_allows(
    tenant_id: str,
    estimated_cost: float,
    credential_kind: str = "company",
) -> bool:
    if not is_wallet_billing_enabled() or credential_kind == "byok":
        return True
    if estimated_cost <= 0:
        return True
    balance = get_balance_sync(tenant_id)
    return balance >= float(estimated_cost)


def deduct_balance_in_session(
    session: Session,
    *,
    tenant_id: str,
    amount: float | Decimal,
    reference_no: str,
    operator: str | None = None,
) -> float:
    """Debit wallet inside caller transaction. Returns balance_after."""
    debit = _decimal(amount)
    if debit <= 0:
        row = _lock_wallet_row(session, tenant_id)
        return float(row.balance or 0.0)

    row = _lock_wallet_row(session, tenant_id)
    balance = _decimal(row.balance or 0)
    version = int(row.version or 0)
    if balance < debit:
        raise InsufficientBalanceError(tenant_id, debit, balance)

    new_balance = balance - debit
    now = datetime.now(UTC).replace(tzinfo=None)
    updated = session.execute(
        _UPDATE_WALLET,
        {
            "balance": new_balance,
            "updated_at": now,
            "tid": tenant_id,
            "version": version,
        },
    )
    if updated.rowcount != 1:
        raise RuntimeError("wallet_version_conflict")

    session.execute(
        _INSERT_TX,
        {
            "tenant_id": tenant_id,
            "type": "consume",
            "amount": -debit,
            "balance_after": new_balance,
            "method": "manual",
            "reference_no": reference_no[:128],
            "operator": operator,
            "created_at": now,
        },
    )
    return float(new_balance)


def recharge_wallet_in_session(
    session: Session,
    *,
    tenant_id: str,
    amount: float | Decimal,
    reference_no: str,
    operator: str,
    method: str = "manual",
    tx_type: str = "recharge",
) -> float:
    credit = _decimal(amount)
    if credit <= 0:
        raise ValueError("recharge_amount_must_be_positive")

    row = _lock_wallet_row(session, tenant_id)
    balance = _decimal(row.balance or 0)
    version = int(row.version or 0)
    new_balance = balance + credit
    now = datetime.now(UTC).replace(tzinfo=None)

    updated = session.execute(
        _UPDATE_WALLET,
        {
            "balance": new_balance,
            "updated_at": now,
            "tid": tenant_id,
            "version": version,
        },
    )
    if updated.rowcount != 1:
        raise RuntimeError("wallet_version_conflict")

    session.execute(
        _INSERT_TX,
        {
            "tenant_id": tenant_id,
            "type": tx_type,
            "amount": credit,
            "balance_after": new_balance,
            "method": method,
            "reference_no": reference_no[:128],
            "operator": operator,
            "created_at": now,
        },
    )
    return float(new_balance)


def recharge_wallet(
    *,
    tenant_id: str,
    amount: float,
    reference_no: str,
    operator: str,
    method: str = "manual",
) -> dict:
    from packages.billing.payment_provider import (
        ManualPaymentProvider,
        RechargeRequest,
    )

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        result = ManualPaymentProvider().recharge(
            session,
            RechargeRequest(
                tenant_id=tenant_id,
                amount=_decimal(amount),
                reference_no=reference_no,
                operator=operator,
                method=method,
            ),
        )
        session.commit()
    return {
        "tenant_id": result.tenant_id,
        "amount": result.amount,
        "balance_after": result.balance_after,
        "reference_no": result.reference_no,
        "method": result.method,
    }


def get_wallet_summary(
    tenant_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        wallet = session.execute(
            text(
                "SELECT balance, currency, updated_at FROM wallets WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        ).fetchone()
        rows = session.execute(
            text(
                """
                SELECT id, type, amount, balance_after, method, reference_no,
                       operator, created_at
                FROM wallet_transactions
                WHERE tenant_id = :tid
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
                """
            ),
            {"tid": tenant_id, "lim": limit, "off": offset},
        ).fetchall()

    return {
        "tenant_id": tenant_id,
        "balance": float(wallet.balance or 0.0) if wallet else 0.0,
        "currency": wallet.currency if wallet else "CNY",
        "updated_at": wallet.updated_at.isoformat() if wallet and wallet.updated_at else None,
        "transactions": [
            {
                "id": r.id,
                "type": r.type,
                "amount": float(r.amount),
                "balance_after": float(r.balance_after),
                "method": r.method,
                "reference_no": r.reference_no,
                "operator": r.operator,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
