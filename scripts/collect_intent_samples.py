#!/usr/bin/env python3
"""Export deduplicated intent samples from audit_logs (Task 65 slice 0).

Usage:
  uv run python scripts/collect_intent_samples.py --tenant-id t_demo --days 1
  uv run python scripts/collect_intent_samples.py --tenant-id t_demo --days 7 --out data/intent/exports/samples.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.intent.services.intent_metrics import (  # noqa: E402
    default_since,
    fetch_intent_samples,
    query_intent_metrics,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect intent samples from audit_logs")
    parser.add_argument("--tenant-id", required=True, help="Tenant id filter")
    parser.add_argument("--days", type=int, default=1, help="Lookback window (default 1)")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Minimum confidence to include in export",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write JSONL samples to file (default stdout summary only)",
    )
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help="Only print distribution metrics JSON",
    )
    args = parser.parse_args()

    since = default_since(args.days)
    until = datetime.utcnow()

    metrics = query_intent_metrics(
        tenant_id=args.tenant_id,
        since=since,
        until=until,
    )

    if args.metrics_only:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return 0

    samples = fetch_intent_samples(
        tenant_id=args.tenant_id,
        since=since,
        until=until,
        min_confidence=args.min_confidence,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            for row in samples:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"Wrote {len(samples)} deduped samples to {args.out}",
            file=sys.stderr,
        )

    summary = {
        **metrics,
        "exported_samples": len(samples),
        "min_confidence": args.min_confidence,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
