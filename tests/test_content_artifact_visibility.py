"""Task 45b.4 — content artifacts default private, explicit tenant share."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.content_ops.artifact_visibility import (
    ArtifactShareForbidden,
    list_visible_artifacts,
    set_artifact_visibility,
)
from packages.content_ops.dig_persist import persist_dig_result
from packages.database.pgvector_session import ContentArtifact


def _dig(*, digest: str = "hash-a", title: str = "北京社保") -> dict:
    return {
        "content_hash": digest,
        "items": [{"title": title, "summary": "摘要", "score": 80}],
        "count": 1,
    }


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    ContentArtifact.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def test_persist_dig_sets_owner_and_private(session: Session) -> None:
    out = persist_dig_result(
        session,
        tenant_id="t1",
        owner_user_id="u1",
        result=_dig(),
        save=True,
    )
    session.commit()
    run = session.get(ContentArtifact, out["run_artifact_id"])
    day = session.get(ContentArtifact, out["day_artifact_id"])
    assert run is not None and day is not None
    assert run.owner_user_id == "u1"
    assert run.visibility == "private"
    assert day.owner_user_id == "u1"
    assert day.visibility == "private"


def test_peer_cannot_list_private_same_tenant(session: Session) -> None:
    persist_dig_result(
        session, tenant_id="t1", owner_user_id="u1", result=_dig(), save=True
    )
    session.commit()
    mine = list_visible_artifacts(session, tenant_id="t1", user_id="u1")
    peer = list_visible_artifacts(session, tenant_id="t1", user_id="u2")
    assert len(mine) >= 2
    assert peer == []


def test_shared_visible_to_peer_unshare_hides(session: Session) -> None:
    out = persist_dig_result(
        session, tenant_id="t1", owner_user_id="u1", result=_dig(), save=True
    )
    session.commit()
    aid = out["run_artifact_id"]
    set_artifact_visibility(
        session, tenant_id="t1", user_id="u1", artifact_id=aid, visibility="shared"
    )
    session.commit()
    peer = list_visible_artifacts(session, tenant_id="t1", user_id="u2")
    assert any(r.id == aid for r in peer)

    set_artifact_visibility(
        session, tenant_id="t1", user_id="u1", artifact_id=aid, visibility="private"
    )
    session.commit()
    peer2 = list_visible_artifacts(session, tenant_id="t1", user_id="u2")
    assert all(r.id != aid for r in peer2)


def test_cross_tenant_cannot_see_shared(session: Session) -> None:
    out = persist_dig_result(
        session, tenant_id="t1", owner_user_id="u1", result=_dig(), save=True
    )
    session.commit()
    set_artifact_visibility(
        session,
        tenant_id="t1",
        user_id="u1",
        artifact_id=out["run_artifact_id"],
        visibility="shared",
    )
    session.commit()
    other = list_visible_artifacts(session, tenant_id="t2", user_id="u9")
    assert other == []


def test_peer_cannot_share_others_private(session: Session) -> None:
    out = persist_dig_result(
        session, tenant_id="t1", owner_user_id="u1", result=_dig(), save=True
    )
    session.commit()
    with pytest.raises(ArtifactShareForbidden):
        set_artifact_visibility(
            session,
            tenant_id="t1",
            user_id="u2",
            artifact_id=out["run_artifact_id"],
            visibility="shared",
        )


def test_two_users_keep_separate_day_collections(session: Session) -> None:
    persist_dig_result(
        session, tenant_id="t1", owner_user_id="u1", result=_dig(), save=True
    )
    persist_dig_result(
        session, tenant_id="t1", owner_user_id="u2", result=_dig(), save=True
    )
    session.commit()
    days = (
        session.query(ContentArtifact)
        .filter_by(tenant_id="t1", kind="hotspot_day")
        .all()
    )
    assert len(days) == 2
    owners = {d.owner_user_id for d in days}
    assert owners == {"u1", "u2"}


def test_idempotent_run_is_per_owner(session: Session) -> None:
    first = persist_dig_result(
        session, tenant_id="t1", owner_user_id="u1", result=_dig(), save=True
    )
    again = persist_dig_result(
        session, tenant_id="t1", owner_user_id="u1", result=_dig(), save=True
    )
    other = persist_dig_result(
        session, tenant_id="t1", owner_user_id="u2", result=_dig(), save=True
    )
    session.commit()
    assert first["idempotent"] is False
    assert again["idempotent"] is True
    assert again["run_artifact_id"] == first["run_artifact_id"]
    assert other["idempotent"] is False
    assert other["run_artifact_id"] != first["run_artifact_id"]
