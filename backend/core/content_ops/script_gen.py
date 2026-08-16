"""script.gen — style + org + hotspots →口播; G7 redaction on exit."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.memory_service import redact_student_names_in_text

logger = logging.getLogger(__name__)


def _style_block(style: dict[str, Any]) -> str:
    parts = [
        f"人设：{style.get('display_name') or '主讲'}（{style.get('persona') or ''}）",
        f"称呼：{', '.join(style.get('addressing') or [])}",
        f"口头禅：{', '.join(style.get('catchphrases') or []) or '无'}",
        f"句长：{style.get('avg_sentence_len') or ''}",
        f"结构：{', '.join(style.get('structure_habits') or [])}",
        f"禁说：{', '.join(style.get('taboos') or [])}",
        f"开场参考：{', '.join(style.get('sample_openers') or [])}",
    ]
    return "\n".join(p for p in parts if p and not p.endswith("（）"))


def _hotspot_block(hotspots: list[dict[str, Any]]) -> str:
    if not hotspots:
        return "（无指定热点，按机构定位自拟一个教育向选题）"
    lines = []
    for i, h in enumerate(hotspots[:5], 1):
        lines.append(
            f"{i}. {h.get('title', '')} — {h.get('summary', '')}"
        )
    return "\n".join(lines)


def _org_block(org: dict[str, Any]) -> str:
    if not org:
        return "（机构画像未配置，按通用教培口吻，不编造具体校名承诺）"
    keys = (
        ("name", "机构"),
        ("industry", "行业"),
        ("product_focus", "产品"),
        ("productFocus", "产品"),
        ("target_audience", "受众"),
        ("targetAudience", "受众"),
    )
    seen: set[str] = set()
    lines = []
    for k, label in keys:
        if k in seen:
            continue
        v = org.get(k)
        if v:
            lines.append(f"{label}：{v}")
            seen.add(k)
    return "\n".join(lines) if lines else "（机构画像较空）"


def build_script_prompt(
    *,
    style: dict[str, Any],
    org_profile: dict[str, Any],
    hotspots: list[dict[str, Any]],
    duration_sec: int = 60,
    platform: str = "短视频",
    extra_instruction: str = "",
) -> str:
    return f"""你是教培机构内容运营助手。请写一篇约{duration_sec}秒的{platform}口播稿。
必须服务本公司内容（勿写成无关个人号）。遵守禁说与合规。

【风格】
{_style_block(style)}

【机构】
{_org_block(org_profile)}

【热点/选题】
{_hotspot_block(hotspots)}

【附加】
{extra_instruction or '无'}

直接输出口播正文，不要标题栏解释。""".strip()


async def generate_script(
    *,
    tenant_id: str,
    style: dict[str, Any],
    org_profile: dict[str, Any],
    hotspots: list[dict[str, Any]] | None = None,
    duration_sec: int = 60,
    platform: str = "短视频",
    extra_instruction: str = "",
    student_names: list[str] | None = None,
    warm: dict[str, str] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """LLM generate + G7 redact. Fail-open on redaction errors."""
    prompt = build_script_prompt(
        style=style,
        org_profile=org_profile,
        hotspots=list(hotspots or []),
        duration_sec=duration_sec,
        platform=platform,
        extra_instruction=extra_instruction,
    )
    text = ""
    try:
        from backend.core.harness import LLMHarness

        harness = LLMHarness()
        model_name = (model or "").strip() or "mock-local"
        chunks: list[str] = []
        async for token in harness.stream(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            tenant_id=tenant_id,
            max_tokens=1200,
        ):
            chunks.append(str(token))
        text = "".join(chunks).strip()
    except Exception:
        logger.exception("script.gen llm failed; using template fallback")
        title = (hotspots or [{}])[0].get("title") if hotspots else None
        opener = (style.get("sample_openers") or ["先问你一个问题……"])[0]
        text = (
            f"{opener}\n"
            f"今天想聊的是：{title or '学习习惯'}。"
            f"结合我们机构的课程服务，给家长三个可立刻用的小方法。"
            f"记住：过程比一次分数更重要。感兴趣的话，评论区留言，我们下期细讲。"
        )

    redacted = False
    try:
        before = text
        text = redact_student_names_in_text(
            text,
            tenant_id=tenant_id,
            names=student_names,
            warm=warm,
        )
        redacted = text != before
    except Exception:
        logger.debug("script.gen G7 skipped", exc_info=True)

    return {
        "script": text,
        "student_pii_redacted": redacted,
        "style_is_default": bool(style.get("is_default")),
        "prompt_chars": len(prompt),
    }
