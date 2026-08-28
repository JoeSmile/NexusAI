"""Intent dataset record I/O."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, TypedDict


class IntentSample(TypedDict, total=False):
    text: str
    label: str
    source: str
    confidence: float
    predicted: str
    label_source: str
    id: str


def normalize_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def sample_key(text: str) -> str:
    return normalize_text(text).lower()


def dedupe_samples(samples: list[IntentSample]) -> list[IntentSample]:
    seen: set[str] = set()
    out: list[IntentSample] = []
    for row in samples:
        text = normalize_text(row.get("text", ""))
        if not text or sample_key(text) in seen:
            continue
        seen.add(sample_key(text))
        item = dict(row)
        item["text"] = text
        out.append(item)
    return out


def load_csv(path: Path) -> list[IntentSample]:
    rows: list[IntentSample] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            text = normalize_text(row.get("text", ""))
            label = (row.get("label") or "").strip()
            if not text or not label:
                continue
            rows.append(
                {
                    "text": text,
                    "label": label,
                    "label_source": row.get("label_source", "seed"),
                }
            )
    return rows


def save_csv(path: Path, samples: list[IntentSample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["text", "label", "label_source"])
        writer.writeheader()
        for row in samples:
            writer.writerow(
                {
                    "text": row["text"],
                    "label": row["label"],
                    "label_source": row.get("label_source", "seed"),
                }
            )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def save_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def file_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]
