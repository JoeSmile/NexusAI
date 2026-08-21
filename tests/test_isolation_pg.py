"""DB-level tenant/user isolation for /memory/me and chat timeline (IDOR)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.core.auth.dual_auth import verify_human_or_legacy_key
from backend.core.auth.models import TenantContext
from backend.core.memory_service import UnifiedMemoryService
from backend.database.pgvector_session import ChatMessage, UserMemory, get_pg_session
from backend.routers.chat_history import router as chat_history_router
from backend.routers.memory import router as memory_router


def _sf():
    sf = get_pg_session()
    with sf.Session() as session:
        session.execute(text("SELECT 1"))
    UserMemory.__table__.create(sf.engine, checkfirst=True)
    ChatMessage.__table__.create(sf.engine, checkfirst=True)
    return sf


def _cleanup(sf, *tenant_ids: str) -> None:
    with sf.Session() as session:
        session.query(UserMemory).filter(UserMemory.tenant_id.in_(tenant_ids)).delete(
            synchronize_session=False
        )
        session.query(ChatMessage).filter(ChatMessage.tenant_id.in_(tenant_ids)).delete(
            synchronize_session=False
        )
        session.commit()


def test_memory_idor_same_tenant_other_user_and_cross_tenant() -> None:
    sf = _sf()
    tid = f"idor-m-{uuid.uuid4().hex[:10]}"
    other = f"idor-x-{uuid.uuid4().hex[:10]}"
    try:
        with sf.Session() as session:
            row = UserMemory(
                tenant_id=tid,
                user_id="ua",
                key="fact:secret",
                value="only-a",
                source="extracted",
            )
            tomb = UserMemory(
                tenant_id=tid,
                user_id="ua",
                key="__forgotten__",
                value="1",
                source="system",
            )
            pending = UserMemory(
                tenant_id=tid,
                user_id="ua",
                key="pending:x",
                value="hold",
                source="extracted",
            )
            session.add_all([row, tomb, pending])
            session.commit()
            mid = int(row.id)

        svc = UnifiedMemoryService(tenant_id=tid)
        listed = asyncio.run(svc.list_warm("ua"))
        keys = [m["key"] for m in listed]
        assert "fact:secret" in keys
        assert "__forgotten__" not in keys
        assert "pending:x" not in keys

        assert asyncio.run(svc.update_warm_value("ub", str(mid), "hacked")) is False
        assert asyncio.run(svc.delete_warm(user_id="ub", memory_id=str(mid))) is False
        assert asyncio.run(svc.update_warm_value("ua", "not-an-id", "x")) is False

        still = asyncio.run(svc.list_warm("ua"))
        by_id = {m["id"]: m for m in still}
        assert by_id[str(mid)]["value"] == "only-a"

        other_svc = UnifiedMemoryService(tenant_id=other)
        assert (
            asyncio.run(other_svc.update_warm_value("ua", str(mid), "hacked"))
            is False
        )

        app = FastAPI()
        app.include_router(memory_router)

        async def _as_b() -> TenantContext:
            return TenantContext(tid, "ub", "user", ["chat:write"], False)

        app.dependency_overrides[verify_human_or_legacy_key] = _as_b
        r = TestClient(app).patch(
            f"/memory/me/memories/{mid}", json={"value": "hacked"}
        )
        assert r.status_code == 404
        listed2 = asyncio.run(svc.list_warm("ua"))
        assert {m["id"]: m for m in listed2}[str(mid)]["value"] == "only-a"
    finally:
        _cleanup(sf, tid, other)


def test_chat_timeline_hides_other_user_and_other_tenant() -> None:
    sf = _sf()
    tid = f"idor-c-{uuid.uuid4().hex[:10]}"
    other = f"idor-ct-{uuid.uuid4().hex[:10]}"
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    try:
        with sf.Session() as session:
            session.add_all(
                [
                    ChatMessage(
                        tenant_id=tid,
                        session_id=sid,
                        user_id="ua",
                        role="user",
                        content="secret-from-a",
                    ),
                    ChatMessage(
                        tenant_id=tid,
                        session_id=sid,
                        user_id="ub",
                        role="user",
                        content="visible-to-b",
                    ),
                    ChatMessage(
                        tenant_id=other,
                        session_id=sid,
                        user_id="ua",
                        role="user",
                        content="other-tenant",
                    ),
                ]
            )
            session.commit()

        app = FastAPI()
        app.include_router(chat_history_router)

        async def _as_b() -> TenantContext:
            return TenantContext(tid, "ub", "user", ["chat:write"], False)

        app.dependency_overrides[verify_human_or_legacy_key] = _as_b
        r = TestClient(app).get(
            "/api/chat/timeline", params={"session_id": sid, "limit": 50}
        )
        assert r.status_code == 200
        blob = str(r.json())
        assert "visible-to-b" in blob
        assert "secret-from-a" not in blob
        assert "other-tenant" not in blob

        r2 = TestClient(app).get(
            "/api/chat/search",
            params={"session_id": sid, "q": "secret"},
        )
        assert r2.status_code == 200
        assert r2.json()["items"] == []
    finally:
        _cleanup(sf, tid, other)
