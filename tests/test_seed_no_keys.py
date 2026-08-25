"""Task 71 slice 2 — seed must never write llm_api_keys."""

from __future__ import annotations

from pathlib import Path

from scripts import seed_pgvector as seed

_SEED_SRC = (
    Path(__file__).resolve().parent.parent / "scripts" / "seed_pgvector.py"
).read_text(encoding="utf-8")


def test_seed_llm_keys_is_noop() -> None:
    # 不应抛错；当前实现只打日志、不写库
    seed.seed_llm_keys()


def test_seed_source_never_inserts_llm_keys() -> None:
    compact = " ".join(_SEED_SRC.lower().split())
    assert "insert into llm_api_keys" not in compact
