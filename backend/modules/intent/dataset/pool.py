"""Golden / train pool builder."""

from __future__ import annotations

import json
import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .augment import augment_samples
from .io import (
    IntentSample,
    dedupe_samples,
    file_content_hash,
    load_csv,
    load_jsonl,
    sample_key,
    save_csv,
    save_jsonl,
)
from .quality import dual_label_kappa_report, pool_balance_report
from .synthetic import generate_synthetic_hardcases

GOLDEN_SIZE = 500
TRAIN_TARGET = 2000


def split_golden_pool(
    samples: list[IntentSample],
    *,
    golden_size: int = GOLDEN_SIZE,
    seed: int = 42,
) -> tuple[list[IntentSample], list[IntentSample]]:
    """Stratified hold-out for frozen golden set."""
    rng = random.Random(seed)
    shuffled = list(samples)
    rng.shuffle(shuffled)

    by_label: dict[str, list[IntentSample]] = {}
    for row in shuffled:
        by_label.setdefault(row["label"], []).append(row)

    labels = sorted(by_label)
    if not labels:
        return [], []

    quota = max(1, golden_size // len(labels))
    golden: list[IntentSample] = []
    remainder: list[IntentSample] = []
    for label in labels:
        rows = by_label[label]
        take = min(quota, len(rows))
        for i, row in enumerate(rows):
            item = dict(row)
            item["label_source"] = "golden_holdout"
            if i < take:
                golden.append(item)
            else:
                remainder.append(row)

    rng.shuffle(remainder)
    while len(golden) < golden_size and remainder:
        item = dict(remainder.pop())
        item["label_source"] = "golden_holdout"
        golden.append(item)

    golden_keys = {sample_key(g["text"]) for g in golden}
    train_seed = [r for r in samples if sample_key(r["text"]) not in golden_keys]
    return golden, dedupe_samples(train_seed)


def build_train_pool(
    *,
    seed_samples: list[IntentSample],
    synthetic: list[IntentSample],
    weak_labels: list[IntentSample],
    high_conf_auto: list[IntentSample],
    human_labeled: list[IntentSample],
    golden_keys: set[str],
    augment_variants: int = 3,
    seed: int = 42,
) -> list[IntentSample]:
    base: list[IntentSample] = []
    for row in seed_samples + synthetic + weak_labels + high_conf_auto + human_labeled:
        if sample_key(row["text"]) in golden_keys:
            continue
        base.append(row)
    base = dedupe_samples(base)
    augmented: list[IntentSample] = []
    for offset in range(2):
        augmented.extend(
            augment_samples(
                base,
                variants_per_row=augment_variants,
                seed=seed + offset,
            )
        )
    return dedupe_samples(base + augmented)


def build_dataset_manifest(
    *,
    golden: list[IntentSample],
    train: list[IntentSample],
    annotation_queue_count: int,
    weak_label_count: int,
    dual_label_rows: list[dict[str, Any]] | None = None,
    version: str = "v1",
) -> dict[str, Any]:
    kappa_report = dual_label_kappa_report(dual_label_rows or [])
    return {
        "version": version,
        "built_at": datetime.now(UTC).isoformat(),
        "golden_size": len(golden),
        "train_size": len(train),
        "annotation_queue_count": annotation_queue_count,
        "weak_label_count": weak_label_count,
        "golden_balance": pool_balance_report(golden, min_per_class=0),
        "train_balance": pool_balance_report(train, min_per_class=300),
        "train_meets_target": len(train) >= TRAIN_TARGET,
        "dual_label_kappa": kappa_report,
        "golden_label_distribution": dict(Counter(r["label"] for r in golden)),
        "train_label_distribution": dict(Counter(r["label"] for r in train)),
    }


def build_golden_dataset(
    *,
    seed_path: Path,
    out_dir: Path,
    audit_jsonl: Path | None = None,
    human_labeled_path: Path | None = None,
    dual_label_path: Path | None = None,
    golden_size: int = GOLDEN_SIZE,
    augment_variants: int = 3,
    seed: int = 42,
) -> dict[str, Any]:
    """Orchestrate golden + train pool outputs under ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pools_dir = out_dir / "pools"
    pools_dir.mkdir(parents=True, exist_ok=True)

    seed_rows = load_csv(seed_path)
    golden, seed_remainder = split_golden_pool(seed_rows, golden_size=golden_size, seed=seed)
    golden_path = out_dir / "golden" / "golden_500.csv"
    save_csv(golden_path, golden)
    golden_keys = {sample_key(r["text"]) for r in golden}

    synthetic = generate_synthetic_hardcases(seed=seed)
    save_jsonl(pools_dir / "synthetic.jsonl", synthetic)

    from .triage import triage_samples

    audit_texts: list[str] = []
    if audit_jsonl is not None and audit_jsonl.is_file():
        audit_texts = [
            str(r.get("query") or r.get("text") or "")
            for r in load_jsonl(audit_jsonl)
        ]
    triage_input = [r["text"] for r in seed_rows] + audit_texts
    triaged = triage_samples(triage_input)

    weak_rows: list[IntentSample] = [
        {
            "text": r["text"],
            "label": r["label"],
            "label_source": "weak_rule",
            "confidence": r.get("confidence"),
        }
        for r in triaged["weak_label"]
    ]
    save_jsonl(pools_dir / "weak_labels.jsonl", weak_rows)
    save_jsonl(pools_dir / "annotation_queue.jsonl", triaged["annotation_queue"])

    human_rows: list[IntentSample] = []
    if human_labeled_path and human_labeled_path.is_file():
        for row in load_jsonl(human_labeled_path):
            text = str(row.get("text") or row.get("query") or "").strip()
            label = str(row.get("label") or "").strip()
            if text and label:
                human_rows.append(
                    {
                        "text": text,
                        "label": label,
                        "label_source": "human",
                    }
                )

    high_conf_rows: list[IntentSample] = [
        {
            "text": r["text"],
            "label": r["label"],
            "label_source": "high_conf_auto",
            "confidence": r.get("confidence"),
        }
        for r in triaged["high_conf_auto"]
    ]

    train = build_train_pool(
        seed_samples=seed_remainder,
        synthetic=synthetic,
        weak_labels=weak_rows,
        high_conf_auto=high_conf_rows,
        human_labeled=human_rows,
        golden_keys=golden_keys,
        augment_variants=augment_variants,
        seed=seed,
    )
    train_path = out_dir / "train" / "train_pool.jsonl"
    save_jsonl(train_path, train)

    dual_rows = load_jsonl(dual_label_path) if dual_label_path and dual_label_path.is_file() else []
    manifest = build_dataset_manifest(
        golden=golden,
        train=train,
        annotation_queue_count=len(triaged["annotation_queue"]),
        weak_label_count=len(weak_rows),
        dual_label_rows=dual_rows,
    )
    manifest["files"] = {
        "golden": str(golden_path),
        "train": str(train_path),
        "golden_hash": file_content_hash(golden_path),
        "train_hash": file_content_hash(train_path),
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
