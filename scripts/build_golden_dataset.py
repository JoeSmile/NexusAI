#!/usr/bin/env python3
"""Build golden_500 + train_pool (Task 65 slice 1).

Usage:
  uv run python scripts/build_golden_dataset.py
  uv run python scripts/build_golden_dataset.py --audit-jsonl data/intent/exports/samples.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.intent.dataset.pool import build_golden_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build golden + train intent datasets")
    parser.add_argument(
        "--seed",
        type=Path,
        default=ROOT / "data" / "intent" / "data_nexusai_seed.csv",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "data" / "intent",
    )
    parser.add_argument("--audit-jsonl", type=Path, default=None)
    parser.add_argument("--human-labeled", type=Path, default=None)
    parser.add_argument("--dual-label", type=Path, default=None)
    parser.add_argument("--golden-size", type=int, default=500)
    parser.add_argument("--augment-variants", type=int, default=5)
    parser.add_argument("--rng-seed", type=int, default=42)
    args = parser.parse_args()

    manifest = build_golden_dataset(
        seed_path=args.seed,
        out_dir=args.out_dir,
        audit_jsonl=args.audit_jsonl,
        human_labeled_path=args.human_labeled,
        dual_label_path=args.dual_label,
        golden_size=args.golden_size,
        augment_variants=args.augment_variants,
        seed=args.rng_seed,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if not manifest.get("train_meets_target"):
        print(
            "WARN: train pool below 2000 — add human labels or increase --augment-variants",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
