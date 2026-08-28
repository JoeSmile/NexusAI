"""Task 52 S5 — template hash merge + replica gate."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from packages.social.templates import (
    template_key_from_structure,
    upsert_template,
)
from backend.database.pgvector_session import Base, SocialTemplate


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[SocialTemplate.__table__])
    Session = sessionmaker(bind=engine)
    with Session() as session:
        yield session


def _structure(ttype: str, *, hook: str = "痛点提问") -> dict:
    return {
        "template_type": ttype,
        "hooks": [hook],
        "outline": [
            {"role": "hook", "text": "提问开场"},
            {"role": "method", "text": "三点干货"},
            {"role": "cta", "text": "关注号召"},
        ],
        "topics": ["学习", "习惯"],
        "replicables": ["三点法"],
        "preview": "填充文案不参与骨架 hash " + "x" * 50,
    }


def test_similar_structures_share_template_key():
    a = _structure("清单式")
    b = _structure("清单式")
    b["preview"] = "完全不同的填充"
    b["replicables"] = ["三点法", "换一个填充点"]  # same count bucket if both <=8... wait replicable_n differs 1 vs 2
    # keep slot counts equal; only fill text differs
    b["replicables"] = ["换一个填充点"]
    assert template_key_from_structure(a) == template_key_from_structure(b)


def test_different_template_type_different_key():
    assert template_key_from_structure(_structure("清单式")) != template_key_from_structure(
        _structure("疑问式")
    )


def test_upsert_merges_sample_count(db_session):
    t1 = upsert_template(
        db_session,
        tenant_id="t1",
        platform="douyin",
        structure=_structure("清单式"),
    )
    t2 = upsert_template(
        db_session,
        tenant_id="t1",
        platform="douyin",
        structure=_structure("清单式"),
    )
    assert t1.id == t2.id
    assert t2.sample_count == 2
    assert db_session.query(SocialTemplate).count() == 1

    # other tenant does not merge
    t3 = upsert_template(
        db_session,
        tenant_id="t2",
        platform="douyin",
        structure=_structure("清单式"),
    )
    assert t3.id != t1.id
    assert t3.sample_count == 1
