"""Task 27: LLM Key 候选链 / 冷却 / 429·401 切 key — 桩模式不连 PG"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import backend.core.key_failover as key_failover
import backend.core.key_repository as key_repo


class _APIStatusError(Exception):
    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code


class _RecordingSession:
    def __init__(self, *, fetchall=None, fetchone=None):
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self._fetchall = fetchall or ([] if fetchall is None else fetchall)
        self._fetchone = fetchone
        self.committed = False

    def execute(self, sql: Any, params: dict[str, object] | None = None):
        sql_s = str(sql)
        self.calls.append((sql_s, params))
        result = MagicMock()
        if "UPDATE" in sql_s.upper():
            result.fetchone = lambda: None
            result.fetchall = lambda: []
            return result
        if self._fetchone is not None and "LIMIT 1" in sql_s.upper():
            result.fetchone = lambda: self._fetchone
            result.fetchall = lambda: [self._fetchone] if self._fetchone else []
            return result
        rows = self._fetchall if isinstance(self._fetchall, list) else []
        result.fetchall = lambda: rows
        result.fetchone = lambda: rows[0] if rows else None
        return result

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _RecordingSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _patch_repo_session(monkeypatch, session: _RecordingSession) -> None:
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(key_repo, "get_pg_session", lambda: factory)


def _row(
    *,
    id: int = 1,
    tenant_id: str = "t1",
    provider: str = "default",
    key_version: int = 1,
    encrypted_key: str = "enc",
    base_url: str = "https://api.example/v1",
    is_active: bool = True,
    expires_at=None,
):
    return SimpleNamespace(
        id=id,
        tenant_id=tenant_id,
        provider=provider,
        key_version=key_version,
        encrypted_key=encrypted_key,
        base_url=base_url,
        is_active=is_active,
        expires_at=expires_at,
    )


@pytest.fixture
def decrypt_ok(monkeypatch):
    km = MagicMock()
    km.decrypt.side_effect = lambda enc: f"plain-{enc}"
    monkeypatch.setattr(key_repo, "KeyManager", lambda: km)


@pytest.mark.asyncio
async def test_get_key_chain_orders_and_limits(monkeypatch, decrypt_ok):
    rows = [
        _row(id=3, key_version=3, encrypted_key="k3"),
        _row(id=2, key_version=2, encrypted_key="k2"),
        _row(id=1, key_version=1, encrypted_key="k1"),
    ]
    session = _RecordingSession(fetchall=rows)
    _patch_repo_session(monkeypatch, session)
    monkeypatch.setattr(key_repo, "_cooldown_seconds", lambda: 60)

    repo = key_repo.LLMKeyRepository()
    chain = await repo.get_key_chain("t1", "default", limit=2)
    assert [k.id for k in chain] == ["3", "2"]
    assert chain[0].api_key == "plain-k3"
    # SQL 含冷却条件与 LIMIT
    sql, params = session.calls[0]
    assert "last_failed_at" in sql
    assert params is not None
    assert params["lim"] == 2
    assert params["cooldown"] == 60


@pytest.mark.asyncio
async def test_get_key_chain_excludes_cooling_keys(monkeypatch, decrypt_ok):
    """行为断言:SQL 含冷却谓词时,桩按 PG 语义排除冷却中 key。"""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    fresh = _row(id=2, key_version=2, encrypted_key="fresh")
    fresh.last_failed_at = None
    cooling = _row(id=1, key_version=1, encrypted_key="cool")
    cooling.last_failed_at = now - timedelta(seconds=10)  # 仍在 60s 冷却内

    class _CoolingSession:
        def __init__(self):
            self.calls: list[tuple[str, dict | None]] = []

        def execute(self, sql, params=None):
            self.calls.append((str(sql), params))
            sql_s = str(sql)
            rows = [fresh, cooling]
            # 若 SQL 丢掉冷却谓词,冷却 key 会泄漏进结果 → 测试失败
            if "last_failed_at" in sql_s and params:
                cooldown = int(params["cooldown"])
                filtered = []
                for r in rows:
                    if getattr(r, "last_failed_at", None) is None:
                        filtered.append(r)
                    elif r.last_failed_at <= now - timedelta(seconds=cooldown):
                        filtered.append(r)
                rows = filtered
            rows = sorted(rows, key=lambda r: -r.key_version)[: int(params["lim"])]
            return MagicMock(fetchall=lambda: rows)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    session = _CoolingSession()
    factory = MagicMock()
    factory.Session.return_value = session
    monkeypatch.setattr(key_repo, "get_pg_session", lambda: factory)
    monkeypatch.setattr(key_repo, "_cooldown_seconds", lambda: 60)

    repo = key_repo.LLMKeyRepository()
    chain = await repo.get_key_chain("t1", "default", limit=3)
    assert [k.id for k in chain] == ["2"]
    assert "last_failed_at" in session.calls[0][0]


@pytest.mark.asyncio
async def test_health_restore_skips_admin_deactivate(monkeypatch):
    """人工停用(failures=0)不应被 verify 成功重新激活。"""
    import backend.core.key_health as kh

    row = SimpleNamespace(
        id=9, encrypted_key="enc", base_url="https://x", is_active=False
    )
    before = SimpleNamespace(consecutive_failures=0, is_active=False)
    updates: list[dict] = []

    class _Sess:
        def __init__(self):
            self.phase = 0

        def execute(self, sql, params=None):
            s = str(sql)
            r = MagicMock()
            if "SELECT *" in s or "encrypted_key" in s and "WHERE id" in s and "consecutive" not in s:
                r.fetchone = lambda: row
            elif "consecutive_failures, is_active" in s:
                r.fetchone = lambda: before
            elif "UPDATE" in s.upper():
                updates.append(dict(params or {}))
                r.fetchone = lambda: None
            else:
                r.fetchone = lambda: row
            return r

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    factory = MagicMock()
    factory.Session.return_value = _Sess()
    monkeypatch.setattr(kh, "get_pg_session", lambda: factory)
    km = MagicMock()
    km.decrypt.return_value = "ok-key"
    monkeypatch.setattr(kh, "KeyManager", lambda: km)

    class _Client:
        def __init__(self, *a, **k):
            pass

        @property
        def models(self):
            async def _list():
                return []

            return SimpleNamespace(list=_list)

    import openai as openai_mod

    monkeypatch.setattr(openai_mod, "AsyncOpenAI", _Client)
    monkeypatch.setattr(kh, "_max_consecutive_failures", lambda: 3)
    monkeypatch.setattr(kh, "_audit_health", lambda *a, **k: None)

    result = await kh.verify_key_by_id(9)
    assert result["status"] == "ok"
    # CASE 用 consecutive_failures >= max_fail 才置 true;failures=0 保持原 is_active
    assert updates
    assert updates[0].get("max_fail") == 3


@pytest.mark.asyncio
async def test_get_key_is_first_of_chain(monkeypatch, decrypt_ok):
    rows = [_row(id=9, key_version=9, encrypted_key="top")]
    session = _RecordingSession(fetchall=rows)
    _patch_repo_session(monkeypatch, session)
    repo = key_repo.LLMKeyRepository()
    key = await repo.get_key("t1", "default")
    assert key is not None
    assert key.id == "9"


@pytest.mark.asyncio
async def test_mark_key_failed_increments_and_deactivates(monkeypatch):
    session = _RecordingSession()
    _patch_repo_session(monkeypatch, session)
    monkeypatch.setattr(key_repo, "_max_consecutive_failures", lambda: 3)

    repo = key_repo.LLMKeyRepository()
    await repo.mark_key_failed(7)
    assert session.committed
    sql, params = session.calls[0]
    assert "consecutive_failures" in sql
    assert "last_failed_at" in sql
    assert params == {"id": 7, "max_fail": 3}


@pytest.mark.asyncio
async def test_clear_key_failure_resets(monkeypatch):
    session = _RecordingSession()
    _patch_repo_session(monkeypatch, session)
    repo = key_repo.LLMKeyRepository()
    await repo.clear_key_failure(5)
    sql, params = session.calls[0]
    assert "consecutive_failures = 0" in sql
    assert params == {"id": 5}


@pytest.mark.asyncio
async def test_failover_429_switches_to_second_key(monkeypatch):
    from backend.core.key_repository import LLMKey

    marks: list[str] = []
    clears: list[str] = []
    used: list[str] = []

    class _Repo:
        async def mark_key_failed(self, key_id):
            marks.append(str(key_id))

        async def clear_key_failure(self, key_id):
            clears.append(str(key_id))

    keys = [
        LLMKey("1", "t", "p", "https://a", "key-a", 2, True, None),
        LLMKey("2", "t", "p", "https://b", "key-b", 1, True, None),
    ]

    async def _call(plain: str, url: str) -> str:
        used.append(plain)
        if plain == "key-a":
            raise _APIStatusError(429)
        return "ok-from-b"

    monkeypatch.setattr(key_failover, "_audit_failover", lambda **kw: None)
    out = await key_failover.call_with_key_failover(
        keys, _call, repo=_Repo(), tenant_id="t", provider="p"  # type: ignore[arg-type]
    )
    assert out == "ok-from-b"
    assert used == ["key-a", "key-b"]
    assert marks == ["1"]
    assert clears == ["2"]


@pytest.mark.asyncio
async def test_failover_5xx_does_not_switch(monkeypatch):
    from backend.core.key_repository import LLMKey

    marks: list[str] = []

    class _Repo:
        async def mark_key_failed(self, key_id):
            marks.append(str(key_id))

        async def clear_key_failure(self, key_id):
            pass

    keys = [
        LLMKey("1", "t", "p", "", "key-a", 2, True, None),
        LLMKey("2", "t", "p", "", "key-b", 1, True, None),
    ]
    used: list[str] = []

    async def _call(plain: str, url: str) -> str:
        used.append(plain)
        raise _APIStatusError(503)

    with pytest.raises(_APIStatusError) as ei:
        await key_failover.call_with_key_failover(
            keys, _call, repo=_Repo(), tenant_id="t"  # type: ignore[arg-type]
        )
    assert ei.value.status_code == 503
    assert used == ["key-a"]
    assert marks == []


def test_classify_switchable_status():
    assert key_failover.classify_switchable_status(_APIStatusError(401)) == 401
    assert key_failover.classify_switchable_status(_APIStatusError(429)) == 429
    assert key_failover.classify_switchable_status(_APIStatusError(500)) is None
    assert key_failover.classify_switchable_status(RuntimeError("nope")) is None


@pytest.mark.asyncio
async def test_load_key_chain_sync_works_under_running_loop(monkeypatch):
    """Important #2: 已有 event loop 时仍能拉到候选链(线程池),不再返回空。"""
    import backend.core.harness.llm_client as llm_client
    from backend.core.key_repository import LLMKey

    async def _fake_chain(tid, provider, limit=3):
        return [
            LLMKey("1", tid, provider, "", "k", 1, True, None),
        ]

    class _Repo:
        async def get_key_chain(self, tid, provider, limit=3):
            return await _fake_chain(tid, provider, limit)

    monkeypatch.setattr(
        "backend.core.key_repository.LLMKeyRepository",
        _Repo,
    )
    chain = llm_client._load_key_chain_sync("t1", "deepseek", limit=3)
    assert len(chain) == 1
    assert chain[0].api_key == "k"


@pytest.mark.asyncio
async def test_llm_generate_passes_key_provider(monkeypatch):
    """Important #1: harness.generate 收到 model registry provider,非写死 default。"""
    from backend.pipeline.nodes import llm_generate as lg
    from backend.pipeline.state import make_initial_state

    captured: dict = {}

    class _H:
        async def generate(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                success=True,
                output="ok",
                latency_ms=1.0,
                error=None,
                metadata={"input_tokens": 1, "output_tokens": 1, "cost": 0.0},
            )

    monkeypatch.setattr(lg, "harness", _H())
    state = make_initial_state("t1", "u1", "s1", "hi")
    state["selected_model"] = "deepseek-v4-flash"
    state["llm_key_provider"] = "deepseek"
    state["finish_reason"] = "routed_to_llm"
    await lg.llm_generate(state)
    assert captured.get("provider") == "deepseek"


@pytest.mark.asyncio
async def test_verify_key_failed_marks_and_may_deactivate(monkeypatch):
    """27.03: verify 失败走 mark_key_failed;达阈值后审计摘除。"""
    import backend.core.key_health as kh

    row = SimpleNamespace(
        id=42,
        encrypted_key="enc",
        base_url="https://api.example",
        is_active=True,
    )
    row_after = SimpleNamespace(is_active=False, consecutive_failures=3)

    class _Sess:
        def __init__(self):
            self.n = 0

        def execute(self, sql, params=None):
            self.n += 1
            r = MagicMock()
            if "consecutive_failures" in str(sql):
                r.fetchone = lambda: row_after
            else:
                r.fetchone = lambda: row
            return r

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    factory = MagicMock()
    factory.Session.return_value = _Sess()
    monkeypatch.setattr(kh, "get_pg_session", lambda: factory)

    km = MagicMock()
    km.decrypt.return_value = "bad-key"
    monkeypatch.setattr(kh, "KeyManager", lambda: km)

    async def _boom(*a, **k):
        raise RuntimeError("auth failed")

    class _Client:
        def __init__(self, *a, **k):
            pass

        @property
        def models(self):
            return SimpleNamespace(list=_boom)

    monkeypatch.setitem(
        __import__("sys").modules,
        "openai",
        SimpleNamespace(AsyncOpenAI=_Client),
    )

    marks: list[int] = []

    class _Repo:
        async def mark_key_failed(self, key_id):
            marks.append(int(key_id))

    monkeypatch.setattr(kh, "LLMKeyRepository", lambda: _Repo())
    monkeypatch.setattr(kh, "_audit_health", lambda *a, **k: None)
    monkeypatch.setattr(kh, "_max_consecutive_failures", lambda: 3)

    # AsyncOpenAI path uses from openai import inside function — patch differently
    import openai as openai_mod

    monkeypatch.setattr(openai_mod, "AsyncOpenAI", _Client)

    result = await kh.verify_key_by_id(42)
    assert result["status"] == "failed"
    assert marks == [42]


def test_failover_sync_401_switches():
    from backend.core.key_repository import LLMKey

    marks: list[str] = []
    clears: list[str] = []

    class _Repo:
        async def mark_key_failed(self, key_id):
            marks.append(str(key_id))

        async def clear_key_failure(self, key_id):
            clears.append(str(key_id))

    keys = [
        LLMKey("10", "t", "p", "", "bad", 2, True, None),
        LLMKey("11", "t", "p", "", "good", 1, True, None),
    ]
    used: list[str] = []

    def _call(plain: str, url: str) -> str:
        used.append(plain)
        if plain == "bad":
            raise _APIStatusError(401)
        return "ok"

    out = key_failover.call_with_key_failover_sync(
        keys, _call, repo=_Repo(), tenant_id="t"  # type: ignore[arg-type]
    )
    assert out == "ok"
    assert used == ["bad", "good"]
    assert marks == ["10"]
    assert clears == ["11"]
