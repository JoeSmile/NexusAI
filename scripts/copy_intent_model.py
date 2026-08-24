#!/usr/bin/env python3
"""Copy v8 intent BERT from intent_project to NexusAI data/models/intent_v8."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = Path(r"D:\LLMs\intent_project\models\intent_model_v8\model")
DEFAULT_DST = ROOT / "data" / "models" / "intent_v8"

EXPECTED_LABELS = 8


def validate_config(model_dir: Path) -> dict:
    config_path = model_dir / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"config.json missing under {model_dir}")
    with config_path.open(encoding="utf-8") as fh:
        cfg = json.load(fh)
    id2label = cfg.get("id2label") or {}
    if len(id2label) != EXPECTED_LABELS:
        raise ValueError(
            f"expected {EXPECTED_LABELS} labels in id2label, got {len(id2label)}"
        )
    return cfg


def copy_model(*, src: Path, dst: Path, force: bool) -> None:
    if not src.is_dir():
        raise FileNotFoundError(f"source model dir not found: {src}")
    validate_config(src)
    if dst.exists():
        if not force:
            raise FileExistsError(
                f"destination exists: {dst} (pass --force to overwrite)"
            )
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    validate_config(dst)
    print(json.dumps({"src": str(src), "dst": str(dst), "labels": EXPECTED_LABELS}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--dst", type=Path, default=DEFAULT_DST)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        copy_model(src=args.src, dst=args.dst, force=args.force)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
