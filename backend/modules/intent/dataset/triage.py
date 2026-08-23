"""Sample triage: weak labels + uncertainty annotation queue."""

from __future__ import annotations

from typing import Any

from backend.modules.intent.core.intent_classifier import IntentClassifier
from backend.modules.intent.core.label_map import normalize_label
from backend.modules.intent.core.rule_engine import RuleBasedIntentEngine

RULE_WEAK_THRESHOLD = 0.85
UNCERTAINTY_LOW = 0.4
UNCERTAINTY_HIGH = 0.7


def triage_query(
    text: str,
    *,
    classifier: IntentClassifier | None = None,
    rule_engine: RuleBasedIntentEngine | None = None,
) -> dict[str, Any]:
    """Classify a query into weak_label / annotation_queue / high_conf_auto / skip."""
    text = (text or "").strip()
    if not text:
        return {"bucket": "skip", "text": text}

    rule_engine = rule_engine or RuleBasedIntentEngine()
    classifier = classifier or IntentClassifier()

    rule_result = rule_engine.detect_intent(text)
    hybrid = classifier.detect_intent(text)

    if rule_result and rule_result.confidence >= RULE_WEAK_THRESHOLD:
        return {
            "bucket": "weak_label",
            "text": text,
            "label": normalize_label(rule_result.intent.value),
            "confidence": float(rule_result.confidence),
            "source": "rule",
            "predicted": hybrid.intent.value,
        }

    conf = float(hybrid.confidence)
    if UNCERTAINTY_LOW <= conf <= UNCERTAINTY_HIGH and (
        rule_result is None or rule_result.confidence < RULE_WEAK_THRESHOLD
    ):
        candidates = [hybrid.intent.value]
        if hybrid.secondary_intents:
            candidates.extend(
                sorted(
                    hybrid.secondary_intents,
                    key=lambda k: hybrid.secondary_intents[k],
                    reverse=True,
                )
            )
        return {
            "bucket": "annotation_queue",
            "text": text,
            "predicted": hybrid.intent.value,
            "confidence": conf,
            "source": str(hybrid.source),
            "candidates": list(dict.fromkeys(candidates))[:3],
        }

    if conf >= RULE_WEAK_THRESHOLD:
        return {
            "bucket": "high_conf_auto",
            "text": text,
            "label": normalize_label(hybrid.intent.value),
            "confidence": conf,
            "source": str(hybrid.source),
            "predicted": hybrid.intent.value,
        }

    return {
        "bucket": "skip",
        "text": text,
        "predicted": hybrid.intent.value,
        "confidence": conf,
        "source": str(hybrid.source),
    }


def triage_samples(
    texts: list[str],
    *,
    classifier: IntentClassifier | None = None,
    rule_engine: RuleBasedIntentEngine | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Batch triage into bucket lists."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "weak_label": [],
        "annotation_queue": [],
        "high_conf_auto": [],
        "skip": [],
    }
    seen: set[str] = set()
    for text in texts:
        key = text.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result = triage_query(
            text,
            classifier=classifier,
            rule_engine=rule_engine,
        )
        buckets[result["bucket"]].append(result)
    return buckets
