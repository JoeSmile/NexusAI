"""成本管理 — 预算检查 + 消费记录"""

from __future__ import annotations

import re

from sqlalchemy import text

from backend.core.metrics import cost_total, tokens_total
from backend.database.pgvector_session import get_pg_session

COST_TABLE: dict[str, float] = {
    "deepseek-v4-flash": 0.00014,
    "deepseek-v4-pro": 0.00055,
    "deepseek-reasoner": 0.00055,
    "gpt-4o": 0.0025,
    "gpt-4o-mini": 0.00015,
    "glm-4": 0.0001,
    "text-embedding-v3": 0.0001,
    "qwen-max": 0.002,
    "default": 0.0005,
}


def _price(model: str) -> float:
    try:
        from backend.core.model_registry import get_model

        spec = get_model(model)
        if spec is not None:
            return float(spec.cost_per_1k)
    except Exception:
        pass
    return COST_TABLE.get(model, COST_TABLE["default"])


def estimate_cost(model: str, max_tokens: int = 1000) -> float:
    """估算一次调用的最大成本"""
    return _price(model) * max_tokens / 1000


def calculate_cost(model: str, total_tokens: int) -> float:
    """计算实际成本"""
    return _price(model) * total_tokens / 1000


def count_tokens(text: str) -> int:
    """粗略 token 计数"""
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    return chinese_chars * 2 + english_chars // 4 + 10


def count_message_tokens(message: dict) -> int:
    """支持纯文本或多模态 content 块。"""
    content = message.get("content", "")
    if isinstance(content, list):
        total = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                total += count_tokens(str(part.get("text", "")))
            elif part.get("type") == "image_url":
                total += 512
        return total
    return count_tokens(str(content))


def record_consumption(
    tenant_id: str,
    cost: float,
    tokens: int,
    model: str = "default",
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """记录消费（Prometheus + billing usage_records）。"""
    cost_total.labels(tenant=tenant_id, model=model).inc(cost)
    tokens_total.labels(tenant=tenant_id, model=model).inc(tokens)
    if input_tokens is None and output_tokens is None:
        input_tokens = tokens
        output_tokens = 0
    elif input_tokens is None:
        input_tokens = max(0, tokens - int(output_tokens or 0))
    elif output_tokens is None:
        output_tokens = max(0, tokens - int(input_tokens or 0))
    try:
        from packages.billing.usage import record_metered_usage

        record_metered_usage(
            tenant_id=tenant_id,
            model=model,
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cost=float(cost),
        )
    except Exception as exc:
        from packages.billing.wallet import InsufficientBalanceError

        if isinstance(exc, InsufficientBalanceError):
            raise


async def check_budget(tenant_id: str, estimated_cost: float) -> bool:
    """检查租户预算是否充足"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        config = session.execute(
            text("SELECT config FROM tenant_config WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).fetchone()

    if not config:
        return True

    budget_config = (config.config or {}).get("budget", {})
    daily_limit = budget_config.get("daily_limit", 10.0)
    if estimated_cost > daily_limit:
        return False
    return True


def cost_summary(
    *,
    tenant_id: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    granularity: str = "day",
) -> dict:
    """按租户/模型/时间窗口聚合 audit_logs 成本。

    granularity: day | hour
    """
    trunc = "hour" if granularity == "hour" else "day"
    clauses = ["1=1"]
    params: dict[str, object] = {}
    if tenant_id:
        clauses.append("tenant_id = :tid")
        params["tid"] = tenant_id
    if from_ts:
        clauses.append("created_at >= CAST(:from_ts AS timestamptz)")
        params["from_ts"] = from_ts
    if to_ts:
        clauses.append("created_at <= CAST(:to_ts AS timestamptz)")
        params["to_ts"] = to_ts
    where = " AND ".join(clauses)

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        by_model = session.execute(
            text(
                f"""
                SELECT COALESCE(NULLIF(model, ''), 'unknown') AS model,
                       COUNT(*) AS calls,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cost), 0) AS cost
                FROM audit_logs
                WHERE {where}
                GROUP BY 1
                ORDER BY cost DESC
                """
            ),
            params,
        ).fetchall()
        by_bucket = session.execute(
            text(
                f"""
                SELECT date_trunc(:trunc, created_at) AS bucket,
                       tenant_id,
                       COUNT(*) AS calls,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens,
                       COALESCE(SUM(cost), 0) AS cost
                FROM audit_logs
                WHERE {where}
                GROUP BY 1, 2
                ORDER BY 1 ASC
                """
            ),
            {**params, "trunc": trunc},
        ).fetchall()
        totals = session.execute(
            text(
                f"""
                SELECT COUNT(*) AS calls,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cost), 0) AS cost
                FROM audit_logs
                WHERE {where}
                """
            ),
            params,
        ).fetchone()

    return {
        "tenant_id": tenant_id,
        "from": from_ts,
        "to": to_ts,
        "granularity": trunc,
        "totals": {
            "calls": int(totals.calls or 0) if totals else 0,
            "input_tokens": int(totals.input_tokens or 0) if totals else 0,
            "output_tokens": int(totals.output_tokens or 0) if totals else 0,
            "cost": float(totals.cost or 0.0) if totals else 0.0,
        },
        "by_model": [
            {
                "model": r.model,
                "calls": int(r.calls),
                "input_tokens": int(r.input_tokens),
                "output_tokens": int(r.output_tokens),
                "cost": float(r.cost),
            }
            for r in by_model
        ],
        "series": [
            {
                "bucket": r.bucket.isoformat() if r.bucket else None,
                "tenant_id": r.tenant_id,
                "calls": int(r.calls),
                "tokens": int(r.tokens),
                "cost": float(r.cost),
            }
            for r in by_bucket
        ],
    }
