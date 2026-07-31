"""成本管理 — 预算检查 + 消费记录"""

from __future__ import annotations

import re

from sqlalchemy import text

from backend.core.metrics import cost_total, tokens_total
from backend.database.pgvector_session import get_pg_session

COST_TABLE: dict[str, float] = {
    "deepseek-chat": 0.00014,
    "deepseek-reasoner": 0.00055,
    "gpt-4o": 0.0025,
    "gpt-4o-mini": 0.00015,
    "glm-4": 0.0001,
    "qwen-max": 0.002,
    "default": 0.0005,
}


def estimate_cost(model: str, max_tokens: int = 1000) -> float:
    """估算一次调用的最大成本"""
    price = COST_TABLE.get(model, COST_TABLE["default"])
    return price * max_tokens / 1000


def calculate_cost(model: str, total_tokens: int) -> float:
    """计算实际成本"""
    price = COST_TABLE.get(model, COST_TABLE["default"])
    return price * total_tokens / 1000


def count_tokens(text: str) -> int:
    """粗略 token 计数"""
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_chars = len(re.findall(r"[a-zA-Z]", text))
    return chinese_chars * 2 + english_chars // 4 + 10


def record_consumption(
    tenant_id: str, cost: float, tokens: int, model: str = "default"
) -> None:
    """记录消费"""
    cost_total.labels(tenant=tenant_id, model=model).inc(cost)
    tokens_total.labels(tenant=tenant_id, model=model).inc(tokens)


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
