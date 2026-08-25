"""Train 8-class intent classifier (65-slice8, 2026-08-24).

Improvements vs train_nexusai.py:
  - 8:1:1 stratified split (train/val/test) + early stopping (patience 3)
  - class weights (imbalanced: after_sales/content_creation are small)
  - confidence tier analysis (>=0.85 / 0.4-0.85 / <0.4) for routing & threshold tuning
  - versioned artifact + report (json + confusion matrix png)
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
import torch
from datasets import Dataset
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix)
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight
from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                          EarlyStoppingCallback, Trainer, TrainingArguments,
                          default_data_collator)

BASE = Path(__file__).resolve().parents[2] / "data" / "intent"
MODEL_BASE = Path(__file__).resolve().parents[2] / "data" / "models" / "bert-base-chinese"
OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "intent_model_v8"

NEW_LABELS = ["greeting", "pre_sales", "after_sales", "content_creation",
              "content_analysis", "knowledge_query", "function", "conversation"]
label2id = {l: i for i, l in enumerate(NEW_LABELS)}
id2label = {i: l for l, i in label2id.items()}

BATCH_SIZE = 32
EPOCHS = 20
LEARNING_RATE = 2e-5
MAX_LENGTH = 48
PATIENCE = 3


def load_rows() -> list[dict]:
    rows = []
    for line in (BASE / "train" / "train_pool_v8.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main() -> None:
    rows = load_rows()
    df = pd.DataFrame(rows)
    df = df[df["label"].isin(NEW_LABELS)]
    df["label_id"] = df["label"].map(label2id)
    print(">> total:", len(df))
    print(">> distribution:", dict(Counter(df["label"])))

    # 8:1:1 stratified
    train_df, tmp_df = train_test_split(df, test_size=0.2, random_state=42, stratify=df["label"])
    val_df, test_df = train_test_split(tmp_df, test_size=0.5, random_state=42, stratify=tmp_df["label"])
    print(f">> split: train={len(train_df)} val={len(val_df)} test={len(test_df)}")

    # class weights for imbalance
    classes = np.array(NEW_LABELS)
    y = df["label"].values
    cw = compute_class_weight("balanced", classes=classes, y=y)
    class_weight_tensor = torch.tensor(cw, dtype=torch.float32)
    print(">> class weights:", dict(zip(NEW_LABELS, np.round(cw, 2))))

    mlflow.set_tracking_uri(f"sqlite:///{Path(__file__).resolve().parents[2].as_posix()}/data/mlflow.db")
    mlflow.set_experiment("intent_recognition_v8")
    mlflow.start_run(run_name=f"v8-{len(train_df)}samples")
    mlflow.log_params({
        "labels": ",".join(NEW_LABELS), "epochs": EPOCHS, "lr": LEARNING_RATE,
        "batch": BATCH_SIZE, "max_len": MAX_LENGTH, "patience": PATIENCE,
        "train_size": len(train_df), "val_size": len(val_df), "test_size": len(test_df),
        "class_weights": json.dumps({k: round(float(v), 3) for k, v in zip(NEW_LABELS, cw)}),
        "base_model": "bert-base-chinese",
    })

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_BASE))
    model = AutoModelForSequenceClassification.from_pretrained(
        str(MODEL_BASE), num_labels=len(NEW_LABELS),
        id2label=id2label, label2id=label2id)

    def tok(examples):
        return tokenizer(examples["text"], padding="max_length", truncation=True, max_length=MAX_LENGTH)

    def make_ds(part: pd.DataFrame) -> Dataset:
        ds = Dataset.from_pandas(part[["text", "label_id"]])
        ds = ds.map(tok, batched=True).rename_column("label_id", "labels")
        ds.set_format("torch", columns=["input_ids", "attention_mask", "labels"])
        return ds

    train_ds, val_ds, test_ds = make_ds(train_df), make_ds(val_df), make_ds(test_df)

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            labels = inputs.pop("labels")
            outputs = model(**inputs)
            logits = outputs.logits
            loss_fct = torch.nn.CrossEntropyLoss(weight=class_weight_tensor.to(logits.device))
            loss = loss_fct(logits, labels)
            return (loss, outputs) if return_outputs else loss

    args = TrainingArguments(
        output_dir=str(OUT_DIR / "ckpt"),
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=BATCH_SIZE * 2,
        learning_rate=LEARNING_RATE,
        weight_decay=0.01,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        logging_steps=20,
        report_to=[],
        fp16=torch.cuda.is_available(),
    )

    trainer = WeightedTrainer(
        model=model, args=args,
        train_dataset=train_ds, eval_dataset=val_ds,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=PATIENCE)],
    )
    print(">> training on", "cuda" if torch.cuda.is_available() else "cpu")
    trainer.train()

    # ---- eval on held-out test ----
    preds = trainer.predict(test_ds)
    logits = preds.predictions
    probs = torch.softmax(torch.tensor(logits), dim=-1).numpy()
    y_pred = logits.argmax(-1)
    y_true = test_df["label_id"].values

    acc = accuracy_score(y_true, y_pred)
    report = classification_report(y_true, y_pred, target_names=NEW_LABELS, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_true, y_pred)
    print(f"\n>> test accuracy: {acc:.4f} | F1 macro: {report['macro avg']['f1-score']:.4f}")

    # ---- confidence tier analysis (routing material) ----
    conf = probs.max(-1)
    tiers = {"high(>=0.85)": conf >= 0.85, "low(0.4-0.85)": (conf >= 0.4) & (conf < 0.85), "fallback(<0.4)": conf < 0.4}
    print("\n>> confidence tiers (routing optimization material):")
    tier_report = {}
    for name, mask in tiers.items():
        n = int(mask.sum())
        if n == 0:
            continue
        t_acc = accuracy_score(y_true[mask], y_pred[mask])
        tier_report[name] = {"n": n, "accuracy": round(float(t_acc), 4)}
        print(f"  {name:18s} n={n:4d} ({n/len(y_true)*100:5.1f}%)  acc={t_acc:.4f}")

    # ---- per-class confusion highlights ----
    print("\n>> per-class F1:")
    for lb in NEW_LABELS:
        print(f"  {lb:20s} F1={report[lb]['f1-score']:.3f}  support={report[lb]['support']:.0f}")

    # ---- save artifacts ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(OUT_DIR / "model"))
    tokenizer.save_pretrained(str(OUT_DIR / "model"))
    summary = {
        "version": "v8", "date": "2026-08-24", "labels": NEW_LABELS,
        "train_size": len(train_df), "val_size": len(val_df), "test_size": len(test_df),
        "accuracy": float(acc), "f1_macro": float(report["macro avg"]["f1-score"]),
        "class_weights": {k: round(float(v), 3) for k, v in zip(NEW_LABELS, cw)},
        "confusion_matrix": cm.tolist(),
        "tiers": tier_report,
        "per_class_f1": {lb: report[lb]["f1-score"] for lb in NEW_LABELS},
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- MLflow: metrics + confusion matrix + artifacts ----
    tier_name_map = {"high(>=0.85)": "high", "low(0.4-0.85)": "low", "fallback(<0.4)": "fallback"}
    tier_metrics = {}
    for k, v in tier_report.items():
        safe = tier_name_map.get(k, k.replace("(", "_").replace(")", "_").replace(">", "_").replace("=", "_").replace("-", "_"))
        tier_metrics[f"tier_{safe}_n"] = v["n"]
        tier_metrics[f"tier_{safe}_acc"] = v["accuracy"]
    mlflow.log_metrics({
        "accuracy": float(acc), "f1_macro": float(report["macro avg"]["f1-score"]),
        **{f"f1_{lb}": report[lb]["f1-score"] for lb in NEW_LABELS},
        **tier_metrics,
    })
    fig, ax = plt.subplots(figsize=(8, 7))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(NEW_LABELS))); ax.set_xticklabels(NEW_LABELS, rotation=45, ha="right")
    ax.set_yticks(range(len(NEW_LABELS))); ax.set_yticklabels(NEW_LABELS)
    ax.set_xlabel("pred"); ax.set_ylabel("true")
    for i in range(len(NEW_LABELS)):
        for j in range(len(NEW_LABELS)):
            ax.text(j, i, cm[i][j], ha="center", va="center",
                    color="white" if cm[i][j] > cm.max() / 2 else "black", fontsize=9)
    fig.tight_layout()
    cm_png = OUT_DIR / "confusion_matrix_v8.png"
    fig.savefig(cm_png, dpi=120)
    plt.close(fig)
    mlflow.log_artifact(str(cm_png))
    mlflow.log_artifacts(str(OUT_DIR / "model"), artifact_path="model")
    mlflow.log_artifact(str(OUT_DIR / "summary.json"))
    mlflow.end_run()
    print(f"\n>> saved to {OUT_DIR} + mlflow run (experiment: intent_recognition_v8)")


if __name__ == "__main__":
    main()
