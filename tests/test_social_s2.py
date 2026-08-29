"""Task 52 S2 — Redis token bucket + pipeline unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.social.rate_limit import BUCKET_KEY, acquire_tikhub_token
from packages.social.types import Content
from packages.database.pgvector_session import (
    Base,
    SocialAccount,
    SocialContent,
    SocialResult,
    SocialTask,
    SocialTemplate,
    SocialUsage,
)


class _FakeRedis:
    """Minimal redis supporting the token-bucket Lua via Python."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, float]] = {}

    def eval(self, script: str, numkeys: int, *args: object) -> list[int | float]:
        del script, numkeys
        key = str(args[0])
        rate = float(args[1])  # type: ignore[arg-type]
        capacity = float(args[2])  # type: ignore[arg-type]
        now_ms = float(args[3])  # type: ignore[arg-type]
        need = float(args[4])  # type: ignore[arg-type]
        data = self.store.get(key) or {"tokens": capacity, "ts": now_ms}
        tokens = float(data["tokens"])
        ts = float(data["ts"])
        elapsed = max(0.0, (now_ms - ts) / 1000.0)
        tokens = min(capacity, tokens + elapsed * rate)
        allowed = 0
        if tokens >= need:
            tokens -= need
            allowed = 1
        self.store[key] = {"tokens": tokens, "ts": now_ms}
        return [allowed, tokens]


def test_token_bucket_limits_to_burst(monkeypatch):
    monkeypatch.setenv("SOCIAL_TIKHUB_QPS", "2")
    monkeypatch.setenv("SOCIAL_TIKHUB_BURST", "4")
    fake = _FakeRedis()
    waits: list[float] = []

    for _ in range(4):
        assert acquire_tikhub_token(
            redis_client=fake, sleep=waits.append, max_wait_s=0.01
        )
    ok = acquire_tikhub_token(redis_client=fake, sleep=waits.append, max_wait_s=0.05)
    assert ok is False
    assert fake.store[BUCKET_KEY]["tokens"] < 1


def test_acquire_for_probe_raises_429(monkeypatch):
    from packages.social.exceptions import TikHubRateLimitError
    from packages.social.rate_limit import acquire_for_probe

    monkeypatch.setenv("SOCIAL_TIKHUB_BURST", "1")
    monkeypatch.setenv("SOCIAL_PROBE_MAX_WAIT_S", "0.05")
    fake = _FakeRedis()
    assert acquire_tikhub_token(redis_client=fake, sleep=lambda _s: None, max_wait_s=1)
    with pytest.raises(TikHubRateLimitError) as ei:
        acquire_for_probe(redis_client=fake, sleep=lambda _s: None)
    assert ei.value.http_status == 429


def test_redis_down_degraded_allows(caplog):
    import logging

    class Boom:
        def eval(self, *a, **k):
            raise RuntimeError("down")

    with caplog.at_level(logging.ERROR):
        ok = acquire_tikhub_token(
            redis_client=Boom(), sleep=lambda _s: None, max_wait_s=1
        )
    assert ok is True
    assert any("social_tikhub_bucket_degraded" in r.message for r in caplog.records)


def test_process_task_rate_limit_requeues_until_cap(db_session, monkeypatch):
    from packages.social import pipeline as pl

    monkeypatch.setenv("SOCIAL_RATE_LIMIT_RETRIES", "3")
    acct = SocialAccount(platform="douyin", account_key="x", external_id="SEC")
    db_session.add(acct)
    db_session.flush()
    task = SocialTask(
        tenant_id="t1",
        user_id="u1",
        platform="douyin",
        account_id=acct.id,
        status="running",
        retry_count=0,
    )
    db_session.add(task)
    db_session.commit()
    tid = task.id

    class FakeConn:
        def fetch_recent(self, *a, **k):
            return []

        def close(self) -> None:
            pass

    # first 3 timeouts → pending with retry_count 1..3
    for expected in (1, 2, 3):
        t = db_session.query(SocialTask).filter(SocialTask.id == tid).one()
        t.status = "running"
        db_session.commit()
        pl.process_task(
            db_session,
            db_session.query(SocialTask).filter(SocialTask.id == tid).one(),
            connector=FakeConn(),  # type: ignore[arg-type]
            acquire=lambda **_: False,
        )
        t = db_session.query(SocialTask).filter(SocialTask.id == tid).one()
        assert t.status == "pending"
        assert t.retry_count == expected
        assert t.leased_at is None

    # 4th → failed
    t = db_session.query(SocialTask).filter(SocialTask.id == tid).one()
    t.status = "running"
    db_session.commit()
    pl.process_task(
        db_session,
        db_session.query(SocialTask).filter(SocialTask.id == tid).one(),
        connector=FakeConn(),  # type: ignore[arg-type]
        acquire=lambda **_: False,
    )
    t = db_session.query(SocialTask).filter(SocialTask.id == tid).one()
    assert t.status == "failed"
    assert t.retry_count == 4


def test_token_bucket_refills(monkeypatch):
    monkeypatch.setenv("SOCIAL_TIKHUB_QPS", "10")
    monkeypatch.setenv("SOCIAL_TIKHUB_BURST", "1")
    fake = _FakeRedis()
    assert acquire_tikhub_token(redis_client=fake, sleep=lambda _s: None, max_wait_s=1)
    # advance fake clock by mutating stored ts backward
    fake.store[BUCKET_KEY]["ts"] -= 500  # 0.5s ago at 10/s → +5 tokens capped at 1
    assert acquire_tikhub_token(redis_client=fake, sleep=lambda _s: None, max_wait_s=1)


def test_mark_task_progress_visible_to_other_session():
    """API poll uses another connection; flush-only progress stays stuck at claim=5%."""
    from sqlalchemy.pool import StaticPool

    from packages.social.queue import mark_task

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine, tables=[SocialAccount.__table__, SocialTask.__table__]
    )
    Session = sessionmaker(bind=engine)
    with Session() as writer:
        acct = SocialAccount(platform="douyin", account_key="k", external_id="SEC")
        writer.add(acct)
        writer.flush()
        task = SocialTask(
            tenant_id="t1",
            user_id="u1",
            platform="douyin",
            account_id=acct.id,
            status="running",
            progress=5,
        )
        writer.add(task)
        writer.commit()
        tid = int(task.id)
        mark_task(writer, task, progress=75)
    with Session() as reader:
        other = reader.query(SocialTask).filter(SocialTask.id == tid).one()
        assert other.progress == 75


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        SocialAccount.__table__,
        SocialContent.__table__,
        SocialTask.__table__,
        SocialResult.__table__,
        SocialUsage.__table__,
        SocialTemplate.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        yield session


def test_pipeline_upsert_and_analyze(db_session, monkeypatch):
    from packages.social import pipeline as pl
    from packages.social.types import AccountInfo

    monkeypatch.setenv("LLM_PROVIDER", "mock")

    acct = SocialAccount(platform="douyin", account_key="jianghushuo", external_id="SEC1")
    db_session.add(acct)
    db_session.flush()
    task = SocialTask(
        tenant_id="t1",
        user_id="u1",
        platform="douyin",
        account_id=acct.id,
        status="running",
    )
    db_session.add(task)
    db_session.commit()

    class FakeConn:
        def probe(self, platform: str, account_key: str) -> AccountInfo:
            return AccountInfo(
                platform="douyin",
                account_key=account_key,
                external_id="SEC1",
                nickname="姜胡说",
            )

        def fetch_recent(self, *a, **k):
            return [
                Content(
                    platform="douyin",
                    external_id="v1",
                    title="t",
                    content="口播" + "文" * 120,
                    content_source="desc",
                    like_count=9,
                ),
                Content(
                    platform="douyin",
                    external_id="v2",
                    title="t2",
                    content="短",
                    content_source="desc",
                    like_count=1,
                ),
            ]

        def close(self) -> None:
            pass

    pl.process_task(
        db_session,
        db_session.query(SocialTask).one(),
        connector=FakeConn(),  # type: ignore[arg-type]
        acquire=lambda **_: True,
    )
    task = db_session.query(SocialTask).one()
    assert task.status == "done"
    assert task.total_count == 2
    assert task.new_count == 2
    assert db_session.query(SocialContent).count() == 2
    assert db_session.query(SocialResult).count() == 2
    assert db_session.query(SocialUsage).count() >= 1

    # second run: same videos → new_count 0, still done
    task2 = SocialTask(
        tenant_id="t1",
        user_id="u1",
        platform="douyin",
        account_id=acct.id,
        status="running",
    )
    db_session.add(task2)
    db_session.commit()
    pl.process_task(
        db_session,
        db_session.query(SocialTask).filter(SocialTask.id == task2.id).one(),
        connector=FakeConn(),  # type: ignore[arg-type]
        acquire=lambda **_: True,
    )
    task2 = db_session.query(SocialTask).filter(SocialTask.id == task2.id).one()
    assert task2.status == "done"
    assert task2.new_count == 0
    assert db_session.query(SocialContent).count() == 2


def test_process_fetch_only_persists_without_llm(db_session, monkeypatch):
    from packages.social import pipeline as pl
    from packages.social.service import FETCH_ONLY
    from packages.social.types import Content as C

    monkeypatch.setenv("LLM_PROVIDER", "openai")  # would fail if analyze ran
    acct = SocialAccount(platform="douyin", account_key="ak", external_id="SEC")
    db_session.add(acct)
    db_session.flush()
    task = SocialTask(
        tenant_id="t1",
        user_id="u1",
        platform="douyin",
        account_id=acct.id,
        status="running",
        error=FETCH_ONLY,
    )
    db_session.add(task)
    db_session.commit()

    class FakeConn:
        def fetch_recent(self, *a, **k):
            return [
                C(
                    platform="douyin",
                    external_id="v1",
                    title="t",
                    content="口播全文" * 20,
                    content_source="desc",
                    like_count=3,
                )
            ]

        def close(self) -> None:
            pass

    analyzed: list[int] = []

    def _builder(content: SocialContent) -> dict:
        analyzed.append(int(content.id))
        return {"stub": True}

    pl.process_task(
        db_session,
        db_session.query(SocialTask).one(),
        connector=FakeConn(),  # type: ignore[arg-type]
        acquire=lambda **_: True,
        structure_builder=_builder,
    )
    task = db_session.query(SocialTask).one()
    assert task.status == "done"
    assert task.new_count == 1
    assert db_session.query(SocialContent).count() == 1
    assert db_session.query(SocialResult).count() == 0
    assert analyzed == []


def test_process_fetch_only_respects_limit(db_session, monkeypatch):
    from packages.social import pipeline as pl
    from packages.social.types import Content as C

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    acct = SocialAccount(platform="douyin", account_key="ak", external_id="SEC")
    db_session.add(acct)
    db_session.flush()
    task = SocialTask(
        tenant_id="t1",
        user_id="u1",
        platform="douyin",
        account_id=acct.id,
        status="running",
        error="[fetch_only:3]",
    )
    db_session.add(task)
    db_session.commit()

    class FakeConn:
        def fetch_recent(self, *a, **k):
            assert k.get("limit") == 3
            return [
                C(platform="douyin", external_id=f"v{i}", title="t", content="x")
                for i in range(10)
            ]

        def close(self) -> None:
            pass

    def _builder(_content: SocialContent) -> dict:
        raise AssertionError("no llm")

    pl.process_task(
        db_session,
        db_session.query(SocialTask).one(),
        connector=FakeConn(),  # type: ignore[arg-type]
        acquire=lambda **_: True,
        structure_builder=_builder,
    )
    task = db_session.query(SocialTask).one()
    assert task.status == "done"
    assert db_session.query(SocialContent).count() == 3
    assert task.total_count == 3


def test_reclaim_stale_uses_leased_at(db_session):
    from packages.social.queue import reclaim_stale_running

    acct = SocialAccount(platform="douyin", account_key="a", external_id="s")
    db_session.add(acct)
    db_session.flush()
    old = datetime.now(UTC) - timedelta(minutes=40)
    task = SocialTask(
        tenant_id="t",
        user_id="u",
        platform="douyin",
        account_id=acct.id,
        status="running",
        leased_at=old,
    )
    db_session.add(task)
    db_session.commit()
    n = reclaim_stale_running(db_session, older_than_minutes=30)
    db_session.commit()
    assert n == 1
    assert db_session.query(SocialTask).one().status == "pending"


def test_usage_price_multiplier(db_session, monkeypatch):
    from packages.social.usage import record_usage

    monkeypatch.setenv("SOCIAL_PRICE_MULTIPLIER", "3.0")
    row = record_usage(
        db_session,
        tenant_id="t",
        user_id="u",
        platform="douyin",
        operation="probe",
        item_count=1,
        cost_usd=Decimal("0.0100"),
    )
    assert row.price_usd == Decimal("0.0300")
