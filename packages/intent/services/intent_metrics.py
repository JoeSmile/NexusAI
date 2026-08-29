"""Intent telemetry queries — shared by API and collector script."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from packages.database.pgvector_session import get_pg_session

LOW_CONFIDENCE_THRESHOLD = 0.7


def query_intent_metrics(
    *,
    tenant_id: str,
    since: datetime,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate intent distribution from audit_logs chat rows."""
    until = until or datetime.utcnow()
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        total_row = session.execute(
            text(
                """
                SELECT COUNT(*) AS total
                FROM audit_logs
                WHERE tenant_id = :tid
                  AND action = 'chat'
                  AND created_at >= :since
                  AND created_at < :until
                  AND intent_predicted IS NOT NULL
                """
            ),
            {"tid": tenant_id, "since": since, "until": until},
        ).mappings().first()
        total = int((total_row or {}).get("total") or 0)

        dist_rows = session.execute(
            text(
                """
                SELECT intent_predicted AS intent,
                       COUNT(*) AS count,
                       AVG(intent_confidence) AS avg_confidence
                FROM audit_logs
                WHERE tenant_id = :tid
                  AND action = 'chat'
                  AND created_at >= :since
                  AND created_at < :until
                  AND intent_predicted IS NOT NULL
                GROUP BY intent_predicted
                ORDER BY count DESC
                """
            ),
            {"tid": tenant_id, "since": since, "until": until},
        ).mappings().all()

        source_rows = session.execute(
            text(
                """
                SELECT COALESCE(intent_source, 'unknown') AS source,
                       COUNT(*) AS count
                FROM audit_logs
                WHERE tenant_id = :tid
                  AND action = 'chat'
                  AND created_at >= :since
                  AND created_at < :until
                  AND intent_predicted IS NOT NULL
                GROUP BY intent_source
                ORDER BY count DESC
                """
            ),
            {"tid": tenant_id, "since": since, "until": until},
        ).mappings().all()

        low_row = session.execute(
            text(
                """
                SELECT COUNT(*) AS low_count
                FROM audit_logs
                WHERE tenant_id = :tid
                  AND action = 'chat'
                  AND created_at >= :since
                  AND created_at < :until
                  AND intent_predicted IS NOT NULL
                  AND COALESCE(intent_confidence, 0) < :threshold
                """
            ),
            {
                "tid": tenant_id,
                "since": since,
                "until": until,
                "threshold": LOW_CONFIDENCE_THRESHOLD,
            },
        ).mappings().first()
        low_count = int((low_row or {}).get("low_count") or 0)

    distribution = [
        {
            "intent": row["intent"],
            "count": int(row["count"]),
            "avg_confidence": round(float(row["avg_confidence"] or 0), 4),
        }
        for row in dist_rows
    ]
    by_source = {row["source"]: int(row["count"]) for row in source_rows}
    low_ratio = round(low_count / total, 4) if total else 0.0

    return {
        "tenant_id": tenant_id,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "total": total,
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        "low_confidence_count": low_count,
        "low_confidence_ratio": low_ratio,
        "distribution": distribution,
        "by_source": by_source,
    }


def fetch_intent_samples(
    *,
    tenant_id: str,
    since: datetime,
    until: datetime | None = None,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    """Export deduplicated chat queries with predicted intent (no response body)."""
    until = until or datetime.utcnow()
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        rows = session.execute(
            text(
                """
                SELECT DISTINCT ON (LOWER(TRIM(input_text)))
                    input_text AS query,
                    intent_predicted AS intent,
                    intent_confidence AS confidence,
                    intent_source AS source,
                    created_at
                FROM audit_logs
                WHERE tenant_id = :tid
                  AND action = 'chat'
                  AND created_at >= :since
                  AND created_at < :until
                  AND intent_predicted IS NOT NULL
                  AND COALESCE(intent_confidence, 0) >= :min_conf
                  AND COALESCE(TRIM(input_text), '') <> ''
                ORDER BY LOWER(TRIM(input_text)), created_at DESC
                """
            ),
            {
                "tid": tenant_id,
                "since": since,
                "until": until,
                "min_conf": min_confidence,
            },
        ).mappings().all()

    return [
        {
            "query": (row["query"] or "")[:2000],
            "intent": row["intent"],
            "confidence": float(row["confidence"] or 0),
            "source": row["source"],
            "created_at": row["created_at"].isoformat()
            if row.get("created_at")
            else None,
        }
        for row in rows
    ]


def default_since(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=max(1, days))
