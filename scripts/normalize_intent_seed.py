#!/usr/bin/env python3
"""Normalize intent seed CSV labels to product 7-class IntentType."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.intent.core.label_map import normalize_sample  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize intent seed labels to 8 classes")
    parser.add_argument(
        "--in",
        dest="in_path",
        type=Path,
        default=ROOT / "data" / "intent" / "data_nexusai_seed.csv",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: overwrite --in)",
    )
    args = parser.parse_args()

    in_path = args.in_path
    out_path = args.out or in_path
    rows_in = list(csv.DictReader(in_path.open(encoding="utf-8")))
    rows_out: list[dict[str, str]] = []
    remapped = Counter()

    for row in rows_in:
        raw = (row.get("label") or "").strip()
        text = (row.get("text") or "").strip()
        normalized = normalize_sample(text, raw)
        if raw.lower() != normalized:
            remapped[f"{raw}->{normalized}"] += 1
        rows_out.append({"text": row.get("text", ""), "label": normalized})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["text", "label"])
        writer.writeheader()
        writer.writerows(rows_out)

    dist = Counter(r["label"] for r in rows_out)
    print(
        json_summary(
            {
                "input": str(in_path),
                "output": str(out_path),
                "rows": len(rows_out),
                "remapped": dict(remapped),
                "distribution": dict(dist),
            }
        )
    )
    return 0


def json_summary(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
