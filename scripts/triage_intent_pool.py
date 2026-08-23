#!/usr/bin/env python3
"""Triage queries into weak-label pool and annotation queue."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.modules.intent.dataset.io import load_jsonl, save_jsonl  # noqa: E402
from backend.modules.intent.dataset.triage import triage_samples  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage intent samples into pools")
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        required=True,
        help="JSONL (query/text) or plain text files",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "data" / "intent" / "pools",
    )
    args = parser.parse_args()

    texts: list[str] = []
    for path in args.input:
        if path.suffix == ".jsonl":
            for row in load_jsonl(path):
                texts.append(str(row.get("query") or row.get("text") or ""))
        else:
            texts.extend(
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )

    buckets = triage_samples(texts)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    save_jsonl(args.out_dir / "weak_labels.jsonl", buckets["weak_label"])
    save_jsonl(args.out_dir / "annotation_queue.jsonl", buckets["annotation_queue"])
    save_jsonl(args.out_dir / "high_conf_auto.jsonl", buckets["high_conf_auto"])

    summary = {k: len(v) for k, v in buckets.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
