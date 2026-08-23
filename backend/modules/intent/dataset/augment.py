"""Text augmentation for intent train pool (train-only; never golden)."""

from __future__ import annotations

import random

from .io import IntentSample

_PREFIXES = ["嗯", "那个", "就是", "请问", "能不能", "帮我"]
_SUFFIXES = ["呗", "呢", "啊", "呀", "哦", "哈"]
_SYNONYMS: dict[str, list[str]] = {
    "查询": ["查一下", "看看", "找找"],
    "制度": ["规定", "政策", "流程"],
    "提醒": ["通知", "叫我", "记得"],
    "建议": ["意见", "方案", "办法"],
    "你好": ["您好", "嗨"],
    "记录": ["记下", "备忘", "保存"],
}


def augment_text(text: str, *, rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    new_text = text
    if rng.random() > 0.5:
        new_text = rng.choice(_PREFIXES) + new_text
    if rng.random() > 0.5:
        new_text = new_text + rng.choice(_SUFFIXES)
    for word, syns in _SYNONYMS.items():
        if word in new_text and rng.random() > 0.6:
            new_text = new_text.replace(word, rng.choice(syns), 1)
    return new_text


def augment_samples(
    samples: list[IntentSample],
    *,
    variants_per_row: int = 2,
    seed: int = 42,
) -> list[IntentSample]:
    """Return augmented copies (originals excluded)."""
    rng = random.Random(seed)
    out: list[IntentSample] = []
    for row in samples:
        text = row["text"]
        label = row["label"]
        for _ in range(variants_per_row):
            aug = augment_text(text, rng=rng)
            if aug != text:
                out.append(
                    {
                        "text": aug,
                        "label": label,
                        "label_source": "augment",
                    }
                )
    return out
