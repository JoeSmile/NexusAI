"""Task 65 slice 0/8 — product 8-class label alignment."""

from __future__ import annotations

import csv
from pathlib import Path

from packages.intent.core.label_map import (
    LEGACY_FINGPT_12_TO_PRODUCT,
    PRODUCT_INTENT_VALUES,
    is_product_label,
    normalize_label,
    normalize_sample,
    split_legacy_advice,
)
from packages.intent.models.intent_models import IntentType

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "data" / "intent" / "data_nexusai_seed.csv"


def test_product_intent_values_are_eight_classes() -> None:
    assert len(PRODUCT_INTENT_VALUES) == 8
    assert PRODUCT_INTENT_VALUES == {i.value for i in IntentType}


def test_legacy_fingpt_maps_to_product_labels() -> None:
    for mapped in LEGACY_FINGPT_12_TO_PRODUCT.values():
        assert is_product_label(mapped)


def test_normalize_label_maps_fingpt_and_aliases() -> None:
    assert normalize_label("qa") == IntentType.KNOWLEDGE_QUERY.value
    assert normalize_label("finance") == IntentType.CONVERSATION.value
    assert normalize_label("weather") == IntentType.CONVERSATION.value
    assert normalize_label("greeting") == IntentType.GREETING.value
    assert normalize_label("chat") == IntentType.CONVERSATION.value
    assert normalize_label("crisis") == IntentType.CONVERSATION.value
    assert normalize_label("") == IntentType.CONVERSATION.value


def test_advice_splits_with_text() -> None:
    assert split_legacy_advice("帮我报个价") == IntentType.PRE_SALES.value
    assert split_legacy_advice("怎么退款") == IntentType.AFTER_SALES.value
    assert split_legacy_advice("分析一下竞品") == IntentType.CONTENT_ANALYSIS.value
    assert normalize_sample("写个口播稿", "function") == IntentType.CONTENT_CREATION.value
    assert normalize_sample("邮箱密码忘了怎么办", "knowledge_query") == IntentType.AFTER_SALES.value
    assert normalize_sample("在吗", "conversation") == IntentType.GREETING.value
    assert normalize_sample("拜拜", "greeting") == IntentType.CONVERSATION.value


def test_seed_csv_labels_are_product_aligned() -> None:
    assert SEED_PATH.is_file(), "data/intent/data_nexusai_seed.csv missing"
    rows = list(csv.DictReader(SEED_PATH.open(encoding="utf-8")))
    assert len(rows) >= 500
    for row in rows:
        label = normalize_sample(row["text"], row["label"])
        assert is_product_label(label)
