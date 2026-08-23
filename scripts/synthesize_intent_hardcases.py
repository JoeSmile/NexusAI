#!/usr/bin/env python3
"""Export synthetic hard cases (Task 65 slice 1)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.modules.intent.dataset.io import save_jsonl  # noqa: E402
from backend.modules.intent.dataset.synthetic import (  # noqa: E402
    generate_llm_hardcases,
    generate_synthetic_hardcases,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic intent hard cases")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "intent" / "pools" / "synthetic.jsonl",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--llm", action="store_true", help="Try LLM expansion (optional)")
    args = parser.parse_args()

    rows = generate_synthetic_hardcases(seed=args.seed)
    if args.llm:
        rows.extend(generate_llm_hardcases())
    save_jsonl(args.out, rows)
    print(json.dumps({"count": len(rows), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
