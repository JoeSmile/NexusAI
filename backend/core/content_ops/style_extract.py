"""Extract content_style JSON from speech transcript text."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.core.content_ops.style import DEFAULT_CONTENT_STYLE

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """从下面的演讲/口播逐字稿中，提取主讲人口语风格，只输出 JSON（不要 markdown）：
{{
  "display_name": "称呼或艺名，未知则空",
  "persona": "一句话人设",
  "addressing": ["常见称呼"],
  "catchphrases": ["口头禅，最多5条"],
  "avg_sentence_len": "句长描述",
  "structure_habits": ["结构习惯，最多5条"],
  "taboos": ["明显禁说或不宜承诺"],
  "sample_openers": ["典型开场，最多3条"]
}}

逐字稿：
"""


def _heuristic_extract(text: str, creator_id: str) -> dict[str, Any]:
    """No-LLM fallback: light patterns + defaults."""
    style = dict(DEFAULT_CONTENT_STYLE)
    style["creator_id"] = creator_id
    style["is_default"] = False
    # Frequent 2–6 char Chinese chunks as weak catchphrase candidates
    tokens = re.findall(r"[\u4e00-\u9fff]{2,6}", text or "")
    freq: dict[str, int] = {}
    for t in tokens:
        if t in ("我们", "你们", "一个", "这个", "那个", "可以", "就是"):
            continue
        freq[t] = freq.get(t, 0) + 1
    top = sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:5]
    catch = [w for w, c in top if c >= 2][:5]
    if catch:
        style["catchphrases"] = catch
    openers = []
    for line in (text or "").splitlines():
        line = line.strip()
        if 6 <= len(line) <= 40:
            openers.append(line)
            if len(openers) >= 3:
                break
    if openers:
        style["sample_openers"] = openers
    style["persona"] = "从稿件启发式提取的口语风格（可再编辑）"
    return style


async def extract_style_from_text(
    *,
    tenant_id: str,
    creator_id: str,
    text: str,
    model: str | None = None,
) -> dict[str, Any]:
    text = (text or "").strip()
    if len(text) < 20:
        out = dict(DEFAULT_CONTENT_STYLE)
        out["creator_id"] = creator_id
        out["is_default"] = False
        out["persona"] = "文本过短，请补充演讲稿后再提取或手改"
        return out

    try:
        from packages.harness import LLMHarness

        harness = LLMHarness()
        model_name = (model or "").strip() or "mock-local"
        chunks: list[str] = []
        async for token in harness.stream(
            model=model_name,
            messages=[{"role": "user", "content": _EXTRACT_PROMPT + text[:8000]}],
            tenant_id=tenant_id,
            max_tokens=800,
        ):
            chunks.append(str(token))
        raw = "".join(chunks).strip()
        # strip ```json fences if any
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not_object")
        style = dict(DEFAULT_CONTENT_STYLE)
        style.update({k: data[k] for k in data if k in DEFAULT_CONTENT_STYLE or k == "display_name"})
        style["creator_id"] = creator_id
        style["is_default"] = False
        return style
    except Exception:
        logger.debug("style extract LLM failed; heuristic", exc_info=True)
        return _heuristic_extract(text, creator_id)
