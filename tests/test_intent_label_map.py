"""Task 65 slice 0 — product 7-class label alignment."""

from __future__ import annotations

import csv
from pathlib import Path

from backend.modules.intent.core.label_map import (
    LEGACY_FINGPT_12_TO_PRODUCT,
    PRODUCT_INTENT_VALUES,
    is_product_label,
    normalize_label,
)
from backend.modules.intent.models.intent_models import IntentType

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "data" / "intent" / "data_nexusai_seed.csv"


def test_product_intent_values_are_seven_classes() -> None:
    assert len(PRODUCT_INTENT_VALUES) == 7
    assert PRODUCT_INTENT_VALUES == {i.value for i in IntentType}


def test_legacy_fingpt_maps_to_product_labels() -> None:
    for mapped in LEGACY_FINGPT_12_TO_PRODUCT.values():
        assert is_product_label(mapped)


def test_normalize_label_maps_fingpt_and_aliases() -> None:
    assert normalize_label("qa") == IntentType.KNOWLEDGE_QUERY.value
    assert normalize_label("finance") == IntentType.CONVERSATION.value
    assert normalize_label("weather") == IntentType.CHAT.value
    assert normalize_label("greeting") == IntentType.GREETING.value
    assert normalize_label("") == IntentType.CONVERSATION.value


def test_seed_csv_labels_are_product_aligned() -> None:
    assert SEED_PATH.is_file(), "data/intent/data_nexusai_seed.csv missing"
    rows = list(csv.DictReader(SEED_PATH.open(encoding="utf-8")))
    assert len(rows) >= 500
    for row in rows:
        label = normalize_label(row["label"])
        assert is_product_label(label)
