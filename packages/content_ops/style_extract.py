"""Extract content_style JSON from speech transcript text."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from packages.content_ops.style import DEFAULT_CONTENT_STYLE

logger = logging.getLogger(__name__)

_EXTRACT_PROMPT = """你是资深内容风格分析师。从下面的演讲/口播逐字稿中，提取主讲人**可迁移的说话方式**——让另一个写手看完这些描述，能模仿出七八分像。不只记"他爱说什么词"，要挖"他怎么把一个意思讲出来"。

【分析纪律 — 防止表面化】
- 所有字段都要**从稿子里的具体表现反推**，不要写"幽默风趣""亲和力强"这类任何主播都适用的空标签。
- 每个抽象判断尽量带一个稿中原句作为证据（格式：判断 —— 例："……"）。
- 逐字稿可能含口水词（嗯/啊/然后），那是节奏的一部分，但不要当口头禅报。

逐字稿：
"""


# 字段清单单独放，便于 LLM 严格按 JSON 输出
_STYLE_SCHEMA_HINT = """
只输出 JSON（不要 markdown、不要解释）：
{
  "display_name": "称呼/艺名，未知则空",
  "persona": "一句话人设——ta 是谁、用什么身份跟你说话（如'带过3000+学生的老教师，像学长一样掏心窝'），要有稿内证据支撑",
  "addressing": ["常见称呼"],
  "catchphrases": ["口头禅，最多5条——要稿里真出现的"],
  "avg_sentence_len": "句长描述（如'短句为主，8-12字，信息密度高'）",
  "structure_habits": ["结构习惯，最多5条——ta 怎么组织一条内容（如'先抛反常识结论再展开'）"],
  "taboos": ["明显禁说或不宜承诺"],
  "sample_openers": ["典型开场，最多3条——尽量接近原话"],

  "explain_style": "怎么讲道理：先抛结论还是先铺垫？爱用什么类比把抽象讲白？例证带原句",
  "example_style": "怎么讲例子：真实故事/假设场景/数字对比？例子通常多长、放在哪？",
  "transition_style": "怎么转场推进：设问/重复上句尾词/直接'第二'？",
  "pacing": "节奏：快慢、停顿习惯、有没有排比/重复制造节奏？",
  "emotional_tone": "情绪基调：是热切/冷静/严厉/温和/幽默？焦虑怎么处理（放大还是点到为止）？",
  "rhetoric": "修辞偏好：爱设问反问？爱具体数字？爱用'是不是''有没有'拉互动？"
}
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
        full_prompt = _EXTRACT_PROMPT + text[:8000] + "\n\n" + _STYLE_SCHEMA_HINT
        async for token in harness.stream(
            model=model_name,
            messages=[{"role": "user", "content": full_prompt}],
            tenant_id=tenant_id,
            max_tokens=1200,
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
