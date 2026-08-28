#!/usr/bin/env python3
"""Evaluate v8 intent BERT on manual holdout set; persist report under data/intent/eval/reports/."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_EVAL = ROOT / "data" / "intent" / "eval" / "intent_v8_manual_holdout.csv"
DEFAULT_REPORT_DIR = ROOT / "data" / "intent" / "eval" / "reports"

LABELS = [
    "greeting",
    "pre_sales",
    "after_sales",
    "content_creation",
    "content_analysis",
    "knowledge_query",
    "function",
    "conversation",
]


def load_eval_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            text = (row.get("text") or "").strip()
            label = (row.get("label") or "").strip()
            if text and label:
                rows.append(
                    {
                        "text": text,
                        "label": label,
                        "note": (row.get("note") or "").strip(),
                    }
                )
    return rows


def macro_f1(per_label: dict[str, dict[str, float]]) -> float:
    f1s = [stats["f1"] for stats in per_label.values() if stats["support"] > 0]
    return sum(f1s) / len(f1s) if f1s else 0.0


def tier_band(conf: float) -> str:
    if conf >= 0.85:
        return "high"
    if conf >= 0.4:
        return "low"
    return "fallback"


def evaluate(
    *,
    eval_path: Path,
    model_path: str | None,
    report_dir: Path,
    report_prefix: str = "intent_v8_eval",
) -> dict:
    from packages.intent.core.intent_classifier import MLIntentClassifier

    eval_path = eval_path.resolve()
    rows = load_eval_rows(eval_path)
    clf = MLIntentClassifier(model_path=model_path)
    if not clf.is_loaded:
        raise RuntimeError(
            "v8 model not loaded — run: uv sync --extra intent-model && "
            "uv run python scripts/copy_intent_model.py --force"
        )

    predictions: list[dict] = []
    confusion: Counter[tuple[str, str]] = Counter()
    label_stats: dict[str, dict[str, float]] = {
        lb: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for lb in LABELS
    }

    for row in rows:
        gold = row["label"]
        result = clf.classify(row["text"])
        pred = result.intent.value
        ok = pred == gold
        confusion[(gold, pred)] += 1
        label_stats[gold]["support"] += 1
        if ok:
            label_stats[gold]["tp"] += 1
        else:
            label_stats[gold]["fn"] += 1
            label_stats[pred]["fp"] += 1
        predictions.append(
            {
                "text": row["text"],
                "gold": gold,
                "pred": pred,
                "correct": ok,
                "confidence": round(result.confidence, 4),
                "tier": tier_band(result.confidence),
                "note": row.get("note", ""),
            }
        )

    per_label: dict[str, dict[str, float]] = {}
    for lb in LABELS:
        tp = label_stats[lb]["tp"]
        fp = label_stats[lb]["fp"]
        fn = label_stats[lb]["fn"]
        support = label_stats[lb]["support"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        per_label[lb] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": int(support),
        }

    correct = sum(1 for p in predictions if p["correct"])
    total = len(predictions)
    high_tier = sum(1 for p in predictions if p["tier"] == "high")
    high_correct = sum(
        1 for p in predictions if p["tier"] == "high" and p["correct"]
    )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "eval_dataset": str(eval_path.relative_to(ROOT.resolve())),
        "model_path": str(clf.model_path),
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "macro_f1": round(macro_f1(per_label), 4),
        "high_tier_count": high_tier,
        "high_tier_accuracy": round(high_correct / high_tier, 4) if high_tier else 0.0,
        "per_label": per_label,
        "misclassified": [p for p in predictions if not p["correct"]],
        "predictions": predictions,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = report_dir / f"{report_prefix}_{stamp}.json"
    md_path = report_dir / f"{report_prefix}_{stamp}.md"
    latest_json = report_dir / f"{report_prefix}_latest.json"
    latest_md = report_dir / f"{report_prefix}_latest.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")

    lines = [
        "# Intent v8 Manual Holdout Evaluation",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dataset: `{report['eval_dataset']}` ({total} samples, hand-written holdout)",
        f"- Model: `{report['model_path']}`",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Accuracy | **{report['accuracy']:.2%}** ({correct}/{total}) |",
        f"| Macro F1 | **{report['macro_f1']:.4f}** |",
        f"| High-tier (≥0.85) accuracy | **{report['high_tier_accuracy']:.2%}** ({high_correct}/{high_tier}) |",
        "",
        "## Per-class",
        "",
        "| Label | P | R | F1 | Support |",
        "|-------|---|---|----|---------|",
    ]
    for lb in LABELS:
        s = per_label[lb]
        lines.append(
            f"| {lb} | {s['precision']:.2f} | {s['recall']:.2f} | {s['f1']:.2f} | {int(s['support'])} |"
        )
    if report["misclassified"]:
        lines.extend(["", "## Misclassified", ""])
        for m in report["misclassified"]:
            lines.append(
                f"- `{m['text']}` — gold **{m['gold']}** → pred **{m['pred']}** "
                f"(conf={m['confidence']}, tier={m['tier']})"
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    report["json_report"] = str(json_path.relative_to(ROOT))
    report["md_report"] = str(md_path.relative_to(ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL)
    parser.add_argument(
        "--boundary",
        type=Path,
        default=None,
        help="Optional boundary-case CSV (same schema)",
    )
    parser.add_argument("--model-path", type=str, default=None)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    try:
        report = evaluate(
            eval_path=args.eval,
            model_path=args.model_path,
            report_dir=args.report_dir,
            report_prefix="intent_v8_eval",
        )
        out = {
            "holdout": {
                "accuracy": report["accuracy"],
                "macro_f1": report["macro_f1"],
                "high_tier_accuracy": report["high_tier_accuracy"],
                "misclassified": len(report["misclassified"]),
                "json_report": report["json_report"],
                "md_report": report["md_report"],
            }
        }
        if args.boundary and args.boundary.is_file():
            boundary = evaluate(
                eval_path=args.boundary,
                model_path=args.model_path,
                report_dir=args.report_dir,
                report_prefix="intent_v8_boundary_eval",
            )
            out["boundary"] = {
                "accuracy": boundary["accuracy"],
                "macro_f1": boundary["macro_f1"],
                "misclassified": boundary["misclassified"],
            }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
