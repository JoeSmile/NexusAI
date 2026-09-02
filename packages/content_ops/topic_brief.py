"""Topic brief — B站开放搜索 + LLM 骨架；禁止编造无来源数字（Task 45b.5）。

数据类要么引用官方、要么标「待核实，以官方为准」。不编造具体个人/院校录取数字。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import requests

from packages.content_ops.artifact_visibility import VISIBILITY_PRIVATE
from packages.database.pgvector_session import ContentArtifact

logger = logging.getLogger(__name__)

UNVERIFIED_HINT = "待核实，以官方为准"
_DIGITS = re.compile(r"\d")
_UA = (
    "Mozilla/5.0 (compatible; NexusAI-TopicBrief/1.0; +https://localhost)"
)

_BRIEF_PROMPT = """你是教培选题编辑。根据选题标题和摘要写素材骨架 JSON（不要 markdown）。
禁止编造具体数字、政策条款号、某校录取数据、真实个人姓名。
数据类要么写「以官方为准」，要么写「待核实，以官方为准」。
案例只写方向（如「在职备考节奏」），不写具体考生。

输出 JSON 对象，键：
background, key_points(数组3-5条), misconceptions(数组), case_directions(数组), risks(数组)
"""


def annotate_unverified_numbers(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return raw
    if "待核实" in raw or "以官方为准" in raw:
        return raw
    if not _DIGITS.search(raw):
        return raw
    return raw + f"（{UNVERIFIED_HINT}）"


def _walk_annotate(value: Any) -> Any:
    if isinstance(value, str):
        return annotate_unverified_numbers(value)
    if isinstance(value, list):
        return [_walk_annotate(v) for v in value]
    if isinstance(value, dict):
        return {k: _walk_annotate(v) for k, v in value.items()}
    return value


def search_bilibili_topics(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Open-web SSR search. Any failure → []. Never blocks brief."""
    q = (query or "").strip()[:80]
    if not q:
        return []
    try:
        r = requests.get(
            "https://search.bilibili.com/all",
            params={"keyword": q},
            timeout=8,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
        )
        if r.status_code >= 400:
            return []
        titles = re.findall(r'"title"\s*:\s*"([^"\\]{8,80})"', r.text)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for t in titles:
            t = re.sub(r"<[^>]+>", "", t).strip()
            if t in seen or len(t) < 8:
                continue
            seen.add(t)
            out.append({"title": t, "play": None, "desc": ""})
            if len(out) >= limit:
                break
        return out
    except Exception:
        logger.debug("bilibili search skipped", exc_info=True)
        return []


def _harness() -> Any:
    from packages.harness import LLMHarness

    return LLMHarness()


def _parse_llm_json(raw: str) -> dict[str, Any]:
    blob = (raw or "").strip()
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?\s*", "", blob)
        blob = re.sub(r"\s*```$", "", blob)
    try:
        row = json.loads(blob)
    except json.JSONDecodeError:
        start, end = blob.find("{"), blob.rfind("}")
        if start >= 0 and end > start:
            try:
                row = json.loads(blob[start : end + 1])
            except json.JSONDecodeError:
                row = {}
        else:
            row = {}
    if not isinstance(row, dict):
        row = {}
    return row


async def generate_topic_brief(
    *,
    tenant_id: str,
    user_id: str,
    title: str,
    summary: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    title = (title or "").strip()[:200]
    summary = (summary or "").strip()[:800]
    bili = search_bilibili_topics(title)
    background = "政策与数据以官方发布为准。"
    key_points: list[str] = ["以省级教育考试院或教育部公开信息为准"]
    misconceptions: list[str] = ["不要轻信无来源录取率"]
    case_directions: list[str] = ["讲备考节奏与材料清单，不写具体个人"]
    risks: list[str] = [UNVERIFIED_HINT]
    try:
        result = await _harness().generate(
            model="",
            messages=[
                {"role": "system", "content": _BRIEF_PROMPT},
                {
                    "role": "user",
                    "content": f"标题：{title}\n摘要：{summary or '（无）'}",
                },
            ],
            tenant_id=tenant_id,
            max_tokens=800,
        )
        if getattr(result, "success", False) and result.output:
            parsed = _parse_llm_json(str(result.output))
            if parsed.get("background"):
                background = str(parsed["background"])
            if isinstance(parsed.get("key_points"), list) and parsed["key_points"]:
                key_points = [str(x) for x in parsed["key_points"] if x][:8]
            if isinstance(parsed.get("misconceptions"), list) and parsed["misconceptions"]:
                misconceptions = [str(x) for x in parsed["misconceptions"] if x][:8]
            if isinstance(parsed.get("case_directions"), list) and parsed["case_directions"]:
                case_directions = [str(x) for x in parsed["case_directions"] if x][:8]
            if isinstance(parsed.get("risks"), list) and parsed["risks"]:
                risks = [str(x) for x in parsed["risks"] if x][:8]
    except Exception:
        logger.debug("topic brief llm skipped", exc_info=True)

    body = _walk_annotate(
        {
            "title": title,
            "summary": summary,
            "bilibili": bili,
            "background": background,
            "key_points": key_points,
            "misconceptions": misconceptions,
            "case_directions": case_directions,
            "risks": risks,
        }
    )
    out: dict[str, Any] = {"kind": "brief", **body, "artifact_id": None}
    if persist:
        from packages.database.pgvector_session import get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            aid = str(uuid.uuid4())
            session.add(
                ContentArtifact(
                    id=aid,
                    tenant_id=tenant_id,
                    kind="brief",
                    title=f"简报 · {title}"[:200],
                    body=body,
                    owner_user_id=user_id,
                    visibility=VISIBILITY_PRIVATE,
                )
            )
            session.commit()
            out["artifact_id"] = aid
    return out
