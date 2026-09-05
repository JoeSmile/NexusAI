#!/usr/bin/env python3
"""Probe local intent BERT. Not a daemon — weights load inside the API process.

Exit 0 only when v8 weights + torch extra load successfully.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _probe(*, model_path: str | None = None) -> dict:
    from packages.intent.core.intent_classifier import (
        MLIntentClassifier,
        resolve_intent_model_path,
    )

    path = resolve_intent_model_path(model_path)
    weights = (path / "config.json").is_file()
    torch_ok = False
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForSequenceClassification  # noqa: F401

        torch_ok = True
    except ImportError:
        pass

    loaded = False
    if weights and torch_ok:
        loaded = MLIntentClassifier(model_path=str(path)).is_loaded

    if loaded:
        hint = "BERT ready; API loads it in-process (no separate intent server)."
    elif not weights:
        hint = (
            "missing data/models/intent_v8/config.json — "
            "run: uv run python scripts/check_intent_model.py --setup"
        )
    elif not torch_ok:
        hint = "uv sync --extra intent-model --extra dev"
    else:
        hint = "weights present but load failed; see logs"

    return {
        "path": str(path),
        "weights": weights,
        "torch": torch_ok,
        "bert_loaded": loaded,
        "backend": "bert" if loaded else "rule_fallback",
        "hint": hint,
    }


def _maybe_copy() -> None:
    from scripts.copy_intent_model import DEFAULT_DST, DEFAULT_SRC, copy_model

    if (DEFAULT_DST / "config.json").is_file():
        return
    copy_model(src=DEFAULT_SRC, dst=DEFAULT_DST, force=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--setup",
        action="store_true",
        help="copy from D:\\LLMs\\intent_project if dest is missing, then probe",
    )
    parser.add_argument("--model-path", default=None)
    args = parser.parse_args()
    if args.setup:
        try:
            _maybe_copy()
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            print(
                "put v8 weights at data/models/intent_v8/ "
                "(or --src via scripts/copy_intent_model.py)",
                file=sys.stderr,
            )
            return 1
        except FileExistsError:
            pass
    result = _probe(model_path=args.model_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["bert_loaded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
