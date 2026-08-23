#!/usr/bin/env python3
"""Validate dual-label agreement (Cohen kappa >= 0.7)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.modules.intent.dataset.io import load_jsonl  # noqa: E402
from backend.modules.intent.dataset.quality import dual_label_kappa_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Dual-label kappa validation")
    parser.add_argument("dual_label_jsonl", type=Path)
    parser.add_argument("--min-kappa", type=float, default=0.7)
    args = parser.parse_args()

    rows = load_jsonl(args.dual_label_jsonl)
    report = dual_label_kappa_report(rows, min_kappa=args.min_kappa)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] or report["pairs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
