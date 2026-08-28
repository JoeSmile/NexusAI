"""Dataset quality metrics."""

from __future__ import annotations

from collections import Counter
from typing import Any

from packages.intent.models.intent_models import IntentType

from .io import IntentSample


def pool_balance_report(
    samples: list[IntentSample],
    *,
    min_per_class: int = 300,
) -> dict[str, Any]:
    dist = Counter(row["label"] for row in samples)
    all_labels = [i.value for i in IntentType]
    per_class = {label: int(dist.get(label, 0)) for label in all_labels}
    deficits = {
        label: max(0, min_per_class - count)
        for label, count in per_class.items()
    }
    return {
        "total": len(samples),
        "per_class": per_class,
        "min_per_class_target": min_per_class,
        "deficits": deficits,
        "balanced": all(count >= min_per_class for count in per_class.values()),
    }


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """Cohen's kappa for two parallel label lists (same length)."""
    if len(labels_a) != len(labels_b) or not labels_a:
        return 0.0
    categories = sorted(set(labels_a) | set(labels_b))
    n = len(labels_a)
    agree = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a == b)
    p_o = agree / n
    dist_a = Counter(labels_a)
    dist_b = Counter(labels_b)
    p_e = sum((dist_a[c] / n) * (dist_b[c] / n) for c in categories)
    if p_e >= 1.0:
        return 1.0 if p_o >= 1.0 else 0.0
    return (p_o - p_e) / (1.0 - p_e)


def dual_label_kappa_report(
    rows: list[dict[str, Any]],
    *,
    label_a_key: str = "label_a",
    label_b_key: str = "label_b",
    min_kappa: float = 0.7,
) -> dict[str, Any]:
    labels_a = [str(r[label_a_key]) for r in rows if label_a_key in r and label_b_key in r]
    labels_b = [str(r[label_b_key]) for r in rows if label_a_key in r and label_b_key in r]
    kappa = cohen_kappa(labels_a, labels_b)
    return {
        "pairs": len(labels_a),
        "kappa": round(kappa, 4),
        "min_kappa_target": min_kappa,
        "passed": kappa >= min_kappa if labels_a else False,
    }
