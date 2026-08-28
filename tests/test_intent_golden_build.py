"""Task 65 slice 1 — golden / train pool builder."""

from __future__ import annotations

from pathlib import Path

from packages.intent.dataset.pool import (
    GOLDEN_SIZE,
    TRAIN_TARGET,
    build_golden_dataset,
    split_golden_pool,
)
from packages.intent.dataset.io import load_csv, load_jsonl

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "intent" / "data_nexusai_seed.csv"


def test_split_golden_pool_size() -> None:
    rows = load_csv(SEED)
    golden, remainder = split_golden_pool(rows, golden_size=GOLDEN_SIZE, seed=42)
    assert len(golden) == GOLDEN_SIZE
    assert len(remainder) < len(rows)


def test_build_golden_dataset_meets_train_target(tmp_path: Path) -> None:
    manifest = build_golden_dataset(
        seed_path=SEED,
        out_dir=tmp_path,
        augment_variants=5,
        seed=42,
    )
    assert manifest["golden_size"] == GOLDEN_SIZE
    assert manifest["train_size"] >= TRAIN_TARGET
    assert (tmp_path / "golden" / "golden_500.csv").is_file()
    train_rows = load_jsonl(tmp_path / "train" / "train_pool.jsonl")
    assert len(train_rows) >= TRAIN_TARGET
