"""S1c — warm read = filter + weight sort + LIMIT; oracle is not old unbounded order."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from packages.database.pgvector_session import UserMemory, get_pg_session
from packages.memory.memory_service import UnifiedMemoryService
from tests.memory_sqlite import sqlite_memory_engine

_DECAY = 0.9
_MIN_W = 0.05


class _SF:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.Session = sessionmaker(bind=engine)


def _oracle(
    rows: list[Any],
    *,
    min_w: float = _MIN_W,
    max_rows: int = 300,
    now: datetime | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """过滤 + 权重排序 + LIMIT + 跳过空 key（方案 §3.2）。"""
    now = now or datetime.utcnow()
    scored: list[tuple[float, datetime | None, Any]] = []
    for r in rows:
        key = getattr(r, "key", None)
        if not key:
            continue
        conf = getattr(r, "confidence", None)
        conf_f = 0.5 if conf is None else float(conf)
        ts = getattr(r, "updated_at", None) or getattr(r, "created_at", None)
        if ts is None:
            days = 0.0
        else:
            naive = ts.replace(tzinfo=None) if getattr(ts, "tzinfo", None) else ts
            days = max(0.0, (now - naive).total_seconds() / 86400.0)
        weight = conf_f * (_DECAY**days)
        if weight < min_w:
            continue
        scored.append((weight, getattr(r, "updated_at", None), r))

    def _sort_key(item: tuple[float, datetime | None, Any]) -> tuple:
        weight, updated, _row = item
        if updated is None:
            return (-weight, True, 0.0)
        naive = (
            updated.replace(tzinfo=None) if getattr(updated, "tzinfo", None) else updated
        )
        return (-weight, False, -naive.timestamp())

    scored.sort(key=_sort_key)
    warm: dict[str, str] = {}
    meta: dict[str, dict[str, Any]] = {}
    for _w, _u, r in scored[:max_rows]:
        warm[r.key] = r.value
        sm = getattr(r, "summary_meta", None)
        if sm:
            meta[r.key] = dict(sm)
    return warm, meta


@pytest.fixture()
def mem_sqlite(monkeypatch: pytest.MonkeyPatch) -> _SF:
    engine = sqlite_memory_engine()
    UserMemory.__table__.create(engine)
    sf = _SF(engine)
    monkeypatch.setattr("packages.memory.memory_service.get_pg_session", lambda: sf)
    return sf


def _insert(
    session,
    *,
    key: str,
    value: str,
    confidence: float | None = 0.9,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    summary_meta: dict | None = None,
    tenant_id: str = "t1",
    user_id: str = "u1",
) -> None:
    now = datetime.utcnow()
    session.add(
        UserMemory(
            tenant_id=tenant_id,
            user_id=user_id,
            key=key,
            value=value,
            confidence=confidence,
            source="test",
            summary_meta=summary_meta,
            created_at=created_at if created_at is not None else now,
            updated_at=updated_at if updated_at is not None else now,
        )
    )


def test_empty_key_skipped(mem_sqlite: _SF, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_WARM_MAX_ROWS", "10")
    with mem_sqlite.Session() as session:
        _insert(session, key="", value="ghost")
        _insert(session, key="keep", value="ok")
        session.commit()
    warm, _meta = UnifiedMemoryService(tenant_id="t1")._read_warm_sync(user_id="u1")
    assert "keep" in warm
    assert "" not in warm


def test_null_confidence_defaults_half(mem_sqlite: _SF, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_WARM_MAX_ROWS", "10")
    with mem_sqlite.Session() as session:
        _insert(session, key="n", value="v", confidence=None)
        session.commit()
        session.execute(text("UPDATE user_memories SET confidence = NULL WHERE key = 'n'"))
        session.commit()
    warm, _meta = UnifiedMemoryService(tenant_id="t1")._read_warm_sync(user_id="u1")
    assert warm.get("n") == "v"


def test_null_updated_at_falls_back_to_created_at(
    mem_sqlite: _SF, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORY_WARM_MAX_ROWS", "10")
    old = datetime.utcnow() - timedelta(days=1)
    with mem_sqlite.Session() as session:
        _insert(session, key="c", value="from-created", created_at=old, updated_at=old)
        session.commit()
        session.execute(text("UPDATE user_memories SET updated_at = NULL WHERE key = 'c'"))
        session.commit()
    warm, _meta = UnifiedMemoryService(tenant_id="t1")._read_warm_sync(user_id="u1")
    assert warm.get("c") == "from-created"


def test_future_timestamp_clamped_not_boosted(
    mem_sqlite: _SF, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GREATEST(0, days)：未来 updated_at 不得把 0.9^负天数打成 > confidence。"""
    monkeypatch.setenv("MEMORY_WARM_MAX_ROWS", "10")
    now = datetime.utcnow()
    with mem_sqlite.Session() as session:
        _insert(
            session,
            key="future",
            value="f",
            confidence=0.5,
            created_at=now,
            updated_at=now + timedelta(days=30),
        )
        _insert(
            session,
            key="present",
            value="p",
            confidence=0.51,
            created_at=now,
            updated_at=now,
        )
        session.commit()
        rows = session.query(UserMemory).filter_by(tenant_id="t1", user_id="u1").all()
    warm, _meta = UnifiedMemoryService(tenant_id="t1")._read_warm_sync(user_id="u1")
    expect, _ = _oracle(rows, max_rows=10, now=datetime.utcnow())
    assert list(warm.keys()) == list(expect.keys())
    # 夹逼后 present(0.51) 仍应排在 future(0.5) 前；未夹逼则 future 权重会 >1
    assert list(warm.keys())[0] == "present"


def test_limit_keeps_top_weights_not_insert_order(
    mem_sqlite: _SF, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORY_WARM_MAX_ROWS", "3")
    now = datetime.utcnow()
    with mem_sqlite.Session() as session:
        _insert(session, key="low", value="1", confidence=0.2, updated_at=now)
        _insert(session, key="mid", value="2", confidence=0.6, updated_at=now)
        _insert(session, key="high", value="3", confidence=0.99, updated_at=now)
        _insert(session, key="also-low", value="4", confidence=0.21, updated_at=now)
        _insert(session, key="also-mid", value="5", confidence=0.61, updated_at=now)
        session.commit()
        rows = session.query(UserMemory).filter_by(tenant_id="t1", user_id="u1").all()
    warm, meta = UnifiedMemoryService(tenant_id="t1")._read_warm_sync(user_id="u1")
    expect, expect_meta = _oracle(rows, max_rows=3, now=datetime.utcnow())
    assert list(warm.keys()) == list(expect.keys())
    assert set(warm) == {"high", "also-mid", "mid"}
    assert "low" not in warm
    assert meta == expect_meta


def test_over_three_hundred_is_truncated(
    mem_sqlite: _SF, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MEMORY_WARM_MAX_ROWS", raising=False)
    now = datetime.utcnow()
    with mem_sqlite.Session() as session:
        for i in range(310):
            _insert(
                session,
                key=f"k{i:04d}",
                value=str(i),
                confidence=0.9,
                updated_at=now - timedelta(seconds=i),
            )
        session.commit()
        rows = session.query(UserMemory).filter_by(tenant_id="t1", user_id="u1").all()
    warm, _meta = UnifiedMemoryService(tenant_id="t1")._read_warm_sync(user_id="u1")
    expect, _ = _oracle(rows, max_rows=300, now=datetime.utcnow())
    assert len(warm) == 300
    assert list(warm.keys()) == list(expect.keys())


def test_sql_filter_off_keeps_unbounded(
    mem_sqlite: _SF, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORY_WARM_SQL_FILTER", "0")
    monkeypatch.setenv("MEMORY_WARM_MAX_ROWS", "3")
    now = datetime.utcnow()
    with mem_sqlite.Session() as session:
        for i in range(5):
            _insert(
                session,
                key=f"u{i}",
                value=str(i),
                confidence=0.8,
                updated_at=now,
            )
        session.commit()
    warm, _meta = UnifiedMemoryService(tenant_id="t1")._read_warm_sync(user_id="u1")
    assert len(warm) == 5


def test_below_min_weight_dropped(mem_sqlite: _SF, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_WARM_MAX_ROWS", "10")
    now = datetime.utcnow()
    with mem_sqlite.Session() as session:
        _insert(
            session,
            key="ancient",
            value="gone",
            confidence=1.0,
            created_at=now - timedelta(days=80),
            updated_at=now - timedelta(days=80),
        )
        _insert(session, key="fresh", value="keep", confidence=1.0, updated_at=now)
        session.commit()
    warm, _meta = UnifiedMemoryService(tenant_id="t1")._read_warm_sync(user_id="u1")
    assert "fresh" in warm
    assert "ancient" not in warm


def _pg_or_skip():
    try:
        sf = get_pg_session()
        with sf.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return sf
    except Exception as exc:
        print(f"test_warm_sql_equiv: skip, postgres unavailable: {exc}")
        pytest.skip("postgres unavailable")


def test_pg_dual_run_matches_oracle(monkeypatch: pytest.MonkeyPatch) -> None:
    sf = _pg_or_skip()
    monkeypatch.delenv("MEMORY_WARM_SQL_FILTER", raising=False)
    monkeypatch.setenv("MEMORY_WARM_MAX_ROWS", "8")
    tenant = f"warm-sql-equiv-{uuid.uuid4().hex[:12]}"
    user = "u-dual"
    now = datetime.utcnow()
    with sf.Session() as session:
        session.query(UserMemory).filter_by(tenant_id=tenant, user_id=user).delete()
        session.commit()
        _insert(
            session,
            key="",
            value="empty",
            tenant_id=tenant,
            user_id=user,
            updated_at=now,
        )
        _insert(
            session,
            key="null-conf",
            value="nc",
            confidence=None,
            tenant_id=tenant,
            user_id=user,
            updated_at=now,
        )
        _insert(
            session,
            key="future",
            value="f",
            confidence=0.4,
            tenant_id=tenant,
            user_id=user,
            created_at=now,
            updated_at=now + timedelta(days=20),
        )
        _insert(
            session,
            key="stale",
            value="s",
            confidence=0.99,
            tenant_id=tenant,
            user_id=user,
            updated_at=now - timedelta(days=2),
        )
        for i in range(12):
            _insert(
                session,
                key=f"bulk{i:02d}",
                value=str(i),
                confidence=0.7 + i * 0.01,
                tenant_id=tenant,
                user_id=user,
                updated_at=now - timedelta(hours=i),
            )
        session.commit()
        session.execute(
            text(
                "UPDATE user_memories SET confidence = NULL "
                "WHERE tenant_id = :tid AND user_id = :uid AND key = 'null-conf'"
            ),
            {"tid": tenant, "uid": user},
        )
        session.execute(
            text(
                "UPDATE user_memories SET updated_at = NULL "
                "WHERE tenant_id = :tid AND user_id = :uid AND key = 'stale'"
            ),
            {"tid": tenant, "uid": user},
        )
        session.commit()
        rows = (
            session.query(UserMemory).filter_by(tenant_id=tenant, user_id=user).all()
        )
    try:
        svc = UnifiedMemoryService(tenant_id=tenant)
        got, got_meta = svc._read_warm_sync(user_id=user)
        expect, expect_meta = _oracle(rows, max_rows=8, now=datetime.utcnow())
        assert list(got.keys()) == list(expect.keys())
        assert got == expect
        assert got_meta == expect_meta
        assert "" not in got
        assert len(got) == 8
    finally:
        with sf.Session() as session:
            session.query(UserMemory).filter_by(tenant_id=tenant, user_id=user).delete()
            session.commit()
