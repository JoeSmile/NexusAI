"""Task 94 S2 — plan_snapshot 语义分离契约测试。

覆盖（对应 plan §5 契约⑥⑦⑧ 的端点层）：
- GET snapshot：streaming（producer 在跑）/ completed（finish 后 bus 释放、registry 终态窗）
- 租户隔离：异租户 GET / DELETE 保温中 run = 404
- DELETE 幂等：未知/已回收 trace 返回 200 ok（评审 F7：不再 404 混淆）
- 保温中 DELETE → 取消标志生效（producer 检查点可中止）
- sweep_expired 惰性清理终态窗后 GET → 404
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.plan_snapshot import router
from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from packages.plan.event_bus import release_run_bus
from packages.plan.run_cancel import is_cancelled
from packages.plan.run_registry import finish as registry_finish
from packages.plan.run_registry import mark_consumer_lost, sweep_expired
from packages.plan.run_registry import register as registry_register


class _FakeTask:
    def __init__(self, done: bool) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


def _tenant(tenant_id: str = "t1") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        role="user",
        extra_permissions=["chat:read", "chat:write"],
        is_cross_tenant=False,
    )


def _client(tenant_id: str = "t1") -> TestClient:
    app = FastAPI()
    app.include_router(router)

    async def _auth() -> TenantContext:
        return _tenant(tenant_id)

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    return TestClient(app)


def _clean(tid: str) -> None:
    release_run_bus(tid)
    sweep_expired(now=1e18)  # 清掉终态窗


def test_snapshot_streaming_status_while_producer_running():
    _clean("t94-s1")
    registry_register("t1", "t94-s1", task=_FakeTask(done=False))
    try:
        res = _client().get("/api/chat/run/t94-s1/snapshot")
        assert res.status_code == 200
        assert res.json()["status"] == "streaming"
    finally:
        _clean("t94-s1")


def test_snapshot_completed_after_finish_without_bus():
    _clean("t94-s2")
    registry_register("t1", "t94-s2", task=_FakeTask(done=True))
    registry_finish("t1", "t94-s2", "completed", keep_s=60)
    try:
        res = _client().get("/api/chat/run/t94-s2/snapshot")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "completed"
        assert body["events"] == []
    finally:
        _clean("t94-s2")


def test_snapshot_404_after_terminal_window_evicted():
    _clean("t94-s3")
    registry_register("t1", "t94-s3", task=_FakeTask(done=True))
    registry_finish("t1", "t94-s3", "completed", keep_s=0.01)
    sweep_expired(now=1e18)  # 惰性清理：超终态窗
    res = _client().get("/api/chat/run/t94-s3/snapshot")
    assert res.status_code == 404


def test_snapshot_cross_tenant_denied():
    _clean("t94-t1")
    registry_register("t1", "t94-t1", task=_FakeTask(done=False))
    try:
        # 异租户 t2 请求 t1 的 run → 404（不泄露存在性）
        res = _client(tenant_id="t2").get("/api/chat/run/t94-t1/snapshot")
        assert res.status_code == 404
        # 同租户正常
        res = _client(tenant_id="t1").get("/api/chat/run/t94-t1/snapshot")
        assert res.status_code == 200
    finally:
        _clean("t94-t1")


def test_cancel_during_warm_sets_flag():
    from packages.plan.run_cancel import clear_cancel

    _clean("t94-c1")
    clear_cancel("t94-c1")
    registry_register("t1", "t94-c1", task=_FakeTask(done=False))
    try:
        res = _client().delete("/api/chat/streaming/t94-c1")
        assert res.status_code == 200
        assert res.json()["cancelled"] is True
        # 保温/streaming 中二次取消：标志真正置位（修复 unregister 时机断链）
        assert is_cancelled("t94-c1") is True
    finally:
        _clean("t94-c1")


def test_cancel_unknown_trace_idempotent_ok():
    res = _client().delete("/api/chat/streaming/no-such-trace-xyz")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_cancel_cross_tenant_denied():
    _clean("t94-c2")
    registry_register("t1", "t94-c2", task=_FakeTask(done=False))
    try:
        res = _client(tenant_id="t2").delete("/api/chat/streaming/t94-c2")
        assert res.status_code == 404
    finally:
        _clean("t94-c2")


# ── Task 94 S4 — 审计字段增强 ─────────────────────────────────────────────


def test_snapshot_resumed_audit_once_after_consumer_lost(monkeypatch):
    """断连后首个恢复轮询落 chat.resumed（带 model/message），且只落一次。"""
    _clean("t94-r1")
    registry_register(
        "t1",
        "t94-r1",
        task=_FakeTask(done=False),
        meta={"model": "deepseek-v4", "message": "帮我写个方案"},
    )
    mark_consumer_lost("t1", "t94-r1")
    rows: list[dict] = []
    monkeypatch.setattr(
        "apps.api.routers.plan_snapshot.write_audit_sync", rows.append
    )
    try:
        res = _client().get("/api/chat/run/t94-r1/snapshot")
        assert res.status_code == 200
        assert res.json()["status"] == "streaming"
        assert [r["action"] for r in rows] == ["chat.resumed"]
        assert rows[0]["model"] == "deepseek-v4"
        assert rows[0]["input_text"] == "帮我写个方案"
        assert rows[0]["output_text"] == "client_resumed"
        # 第二次轮询不再审计（有且仅一次）
        res2 = _client().get("/api/chat/run/t94-r1/snapshot")
        assert res2.status_code == 200
        assert len(rows) == 1
    finally:
        _clean("t94-r1")


def test_snapshot_no_resumed_audit_without_consumer_lost(monkeypatch):
    _clean("t94-r2")
    registry_register("t1", "t94-r2", task=_FakeTask(done=False))
    rows: list[dict] = []
    monkeypatch.setattr(
        "apps.api.routers.plan_snapshot.write_audit_sync", rows.append
    )
    try:
        res = _client().get("/api/chat/run/t94-r2/snapshot")
        assert res.status_code == 200
        assert rows == []
    finally:
        _clean("t94-r2")


def test_delete_audits_cancel_request_with_meta(monkeypatch):
    """DELETE=取消请求面审计（chat.cancel_request）；终态 cancelled 由 producer 侧承载。"""
    _clean("t94-c3")
    registry_register(
        "t1",
        "t94-c3",
        task=_FakeTask(done=False),
        meta={"model": "deepseek-v4", "message": "帮我查一下政策"},
    )
    rows: list[dict] = []
    monkeypatch.setattr(
        "apps.api.routers.plan_snapshot.write_audit_sync", rows.append
    )
    try:
        res = _client().delete("/api/chat/streaming/t94-c3")
        assert res.status_code == 200
        assert [r["action"] for r in rows] == ["chat.cancel_request"]
        assert rows[0]["error_code"] == "CHAT_CANCELLED"
        assert rows[0]["model"] == "deepseek-v4"
        assert rows[0]["input_text"] == "帮我查一下政策"
    finally:
        _clean("t94-c3")


def test_delete_unknown_trace_audits_cancel_request_without_meta(monkeypatch):
    rows: list[dict] = []
    monkeypatch.setattr(
        "apps.api.routers.plan_snapshot.write_audit_sync", rows.append
    )
    res = _client().delete("/api/chat/streaming/no-such-trace-xyz")
    assert res.status_code == 200
    assert [r["action"] for r in rows] == ["chat.cancel_request"]
    assert rows[0]["input_text"] == ""
