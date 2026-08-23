#!/usr/bin/env python3
"""Interactive intent annotation for uncertainty-sampled queue (Task 65 slice 1)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.modules.intent.core.label_map import normalize_label  # noqa: E402
from backend.modules.intent.dataset.io import load_jsonl, save_jsonl  # noqa: E402
from backend.modules.intent.models.intent_models import IntentType


def _load_done_keys(path: Path) -> set[str]:
    done: set[str] = set()
    for row in load_jsonl(path):
        text = str(row.get("text") or row.get("query") or "").strip().lower()
        if text:
            done.add(text)
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description="Annotate intent samples interactively")
    parser.add_argument(
        "--queue",
        type=Path,
        default=ROOT / "data" / "intent" / "pools" / "annotation_queue.jsonl",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "intent" / "pools" / "human_labeled.jsonl",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max items to annotate (0=all)")
    args = parser.parse_args()

    queue = load_jsonl(args.queue)
    if not queue:
        print(f"No queue at {args.queue}", file=sys.stderr)
        return 1

    done = _load_done_keys(args.out)
    labels = [i.value for i in IntentType]
    labeled: list[dict] = []
    count = 0

    for item in queue:
        text = str(item.get("text") or "").strip()
        if not text or text.lower() in done:
            continue
        predicted = item.get("predicted", "")
        candidates = item.get("candidates") or [predicted]
        print("\n---")
        print(f"文本: {text}")
        print(f"预测: {predicted} (conf={item.get('confidence')})")
        print(f"候选: {', '.join(candidates)}")
        print(f"标签: {', '.join(f'{i}:{v}' for i, v in enumerate(labels))}")
        choice = input("输入标签名 / 编号 / s跳过 / q退出: ").strip()
        if choice.lower() == "q":
            break
        if choice.lower() == "s" or not choice:
            continue
        if choice.isdigit():
            idx = int(choice)
            if 0 <= idx < len(labels):
                label = labels[idx]
            else:
                print("无效编号")
                continue
        else:
            label = normalize_label(choice)
        labeled.append({"text": text, "label": label, "label_source": "human"})
        done.add(text.lower())
        count += 1
        if args.limit and count >= args.limit:
            break

    if labeled:
        existing = load_jsonl(args.out)
        save_jsonl(args.out, existing + labeled)
        print(f"Wrote {len(labeled)} labels to {args.out}")
    else:
        print("No new labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
