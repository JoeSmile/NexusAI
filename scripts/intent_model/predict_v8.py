"""Predict with v8 model: single query + golden batch hit-rate + tier routing.

Usage:
  python predict_v8.py "你们产品多少钱"      # single query
  python predict_v8.py --eval-golden       # run golden_v8.csv through model
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "intent_v8" / "model"
GOLDEN = Path(__file__).resolve().parents[2] / "data" / "intent" / "golden" / "golden_v8.csv"

NEW_LABELS = ["greeting", "pre_sales", "after_sales", "content_creation",
              "content_analysis", "knowledge_query", "function", "conversation"]

HIGH = 0.85
LOW = 0.4


def load():
    tok = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    model = AutoModelForSequenceClassification.from_pretrained(str(MODEL_DIR))
    model.eval()
    if torch.cuda.is_available():
        model = model.cuda()
    return tok, model


def predict(tok, model, text: str) -> tuple[str, float]:
    enc = tok(text, return_tensors="pt", truncation=True, max_length=48)
    if torch.cuda.is_available():
        enc = {k: v.cuda() for k, v in enc.items()}
    with torch.no_grad():
        logits = model(**enc).logits
    probs = torch.softmax(logits, dim=-1)[0]
    idx = int(probs.argmax())
    return NEW_LABELS[idx], float(probs[idx])


def tier(p: float) -> str:
    if p >= HIGH:
        return "high(>=0.85)"
    if p >= LOW:
        return "low(0.4-0.85)"
    return "fallback(<0.4)"


def main() -> None:
    tok, model = load()
    if len(sys.argv) > 1 and sys.argv[1] == "--eval-golden":
        from collections import Counter
        rows = list(csv.DictReader(GOLDEN.open(encoding="utf-8")))
        correct = Counter()
        total = Counter()
        for r in rows:
            p, conf = predict(tok, model, r["text"])
            total[r["label"]] += 1
            if p == r["label"]:
                correct[r["label"]] += 1
        print("=== golden_v8 hit-rate ===")
        all_c = sum(correct.values())
        all_t = len(rows)
        print(f"  overall: {all_c}/{all_t} = {all_c / all_t:.4f}")
        for lb in NEW_LABELS:
            c, t = correct[lb], total[lb]
            print(f"  {lb:20s} {c:3d}/{t:<3d} = {c / t:.4f}" if t else f"  {lb:20s} n/a")
        return
    text = sys.argv[1]
    p, conf = predict(tok, model, text)
    print(f"query: {text}\npred:  {p}  (conf={conf:.3f}, tier={tier(conf)})")


if __name__ == "__main__":
    main()
