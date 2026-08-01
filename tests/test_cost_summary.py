"""cost_summary SQL 参数拼装测试（Task 22.02）— 不连真 PG"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import backend.core.cost_manager as cost_manager


class _RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, object] | None]] = []

    def execute(self, sql: Any, params: dict[str, object] | None = None):
        self.calls.append((str(sql), params))
        # by_model / by_bucket → list; totals → one row
        if "date_trunc" in str(sql):
            return MagicMock(fetchall=lambda: [])
        if "GROUP BY 1" in str(sql) and "date_trunc" not in str(sql):
            return MagicMock(fetchall=lambda: [])
        return MagicMock(
            fetchone=lambda: SimpleNamespace(
                calls=0, input_tokens=0, output_tokens=0, cost=0.0
            )
        )

    def __enter__(self) -> _RecordingSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _patch_session(monkeypatch, session: _RecordingSession) -> None:
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(cost_manager, "get_pg_session", lambda: factory)


def test_cost_summary_no_filters(monkeypatch):
    session = _RecordingSession()
    _patch_session(monkeypatch, session)
    out = cost_manager.cost_summary()
    assert out["granularity"] == "day"
    assert out["totals"]["calls"] == 0
    # 三次查询参数均无 tenant / 时间窗
    for _sql, params in session.calls:
        assert "tid" not in (params or {})
        assert "from_ts" not in (params or {})
        assert "to_ts" not in (params or {})


def test_cost_summary_tenant_only(monkeypatch):
    session = _RecordingSession()
    _patch_session(monkeypatch, session)
    cost_manager.cost_summary(tenant_id="acme")
    for _sql, params in session.calls:
        assert params is not None
        assert params.get("tid") == "acme"


def test_cost_summary_time_window(monkeypatch):
    session = _RecordingSession()
    _patch_session(monkeypatch, session)
    cost_manager.cost_summary(
        from_ts="2026-08-01T00:00:00Z",
        to_ts="2026-08-02T00:00:00Z",
    )
    for _sql, params in session.calls:
        assert params is not None
        assert params.get("from_ts") == "2026-08-01T00:00:00Z"
        assert params.get("to_ts") == "2026-08-02T00:00:00Z"
        assert "tenant_id = :tid" not in _sql


def test_cost_summary_hour_granularity(monkeypatch):
    session = _RecordingSession()
    _patch_session(monkeypatch, session)
    out = cost_manager.cost_summary(granularity="hour")
    assert out["granularity"] == "hour"
    bucket_call = next(c for c in session.calls if "date_trunc" in c[0])
    assert bucket_call[1] is not None
    assert bucket_call[1].get("trunc") == "hour"
