"""Task 65 slice 8 leftover: golden_v8 labels must match product IntentType (8-class)."""

from __future__ import annotations

import csv
from pathlib import Path

from backend.modules.intent.models.intent_models import IntentType

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_V8 = ROOT / "data" / "intent" / "golden" / "golden_v8.csv"
ALLOWED = {m.value for m in IntentType}
LEGACY = {"crisis", "advice", "chat"}


def test_golden_v8_labels_match_intent_type() -> None:
    assert GOLDEN_V8.is_file()
    rows = list(csv.DictReader(GOLDEN_V8.open(encoding="utf-8")))
    assert len(rows) >= 500
    labels = {str(r.get("label") or "").strip() for r in rows}
    labels.discard("")
    unexpected = labels - ALLOWED
    assert not unexpected, f"golden_v8 has labels outside IntentType: {sorted(unexpected)}"
    leaked = labels & LEGACY
    assert not leaked, f"golden_v8 still has 7-class names: {sorted(leaked)}"
    missing = ALLOWED - labels
    assert not missing, f"golden_v8 missing IntentType classes: {sorted(missing)}"


def test_legacy_golden_500_is_not_v8_canonical() -> None:
    """旧冻结仍是 7 类；线上/门禁用 golden_v8，勿把 manifest.json 当 v8 真源。"""
    legacy = ROOT / "data" / "intent" / "golden" / "golden_500.csv"
    assert legacy.is_file()
    labels = {
        str(r.get("label") or "").strip()
        for r in csv.DictReader(legacy.open(encoding="utf-8"))
    }
    labels.discard("")
    assert labels & LEGACY, "golden_500 should still be the 7-class freeze (document, do not remap here)"
