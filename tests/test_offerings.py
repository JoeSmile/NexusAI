"""Offerings seed + list."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.content_ops.offerings import (
    DEFAULT_OFFERINGS,
    ensure_default_offerings,
    list_offerings,
)
from backend.database.pgvector_session import Base, Offering


def test_ensure_and_list_offerings():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Offering.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as session:
        n = ensure_default_offerings(session)
        assert n == len(DEFAULT_OFFERINGS)
        session.commit()
        items = list_offerings(session, tenant_id="t1", dept="content_growth")
        assert len(items) >= 2
        ids = {i["id"] for i in items}
        assert "wf.hotspot_dig" in ids
        assert "wf.script_gen" in ids
        implemented = [i for i in items if i["status"] == "implemented"]
        assert all(i["target_id"] for i in implemented)
