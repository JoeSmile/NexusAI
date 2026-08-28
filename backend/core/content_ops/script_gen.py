"""script.gen — style + org + hotspots →口播; G7 redaction on exit."""

from __future__ import annotations

import logging
from typing import Any

from packages.memory.memory_service import redact_student_names_in_text

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
        ("target_region", "地域"),
        ("targetRegion", "地域"),
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


_METHODOLOGY = """【写作方法论 — 短视频口播核心,必须遵守】
这是短视频口播稿,不是文章、不是说明书。按"黄金结构"写:

① 钩子(前 3 秒,决定生死):第一句必须抓住人,四选一:
   - 痛点提问:"你家孩子是不是又拖到11点才写完作业?"
   - 反常识/冲突:"90%的人复习考研,第一步就错了"
   - 数字冲击:"考研报名438万,录取率不到3成"
   - 身份代入:"在职考研的姐妹,这条视频一定看完"
   禁止平淡开场("大家好/今天我们来聊聊/今天讲一下……")。

② 痛点放大(1-2 句):把观众的具体困境说透,让人点头。
   要场景化("深夜一边刷手机一边焦虑""报了班不敢跟老板说请假"),
   不要空喊("很多家长很焦虑")。

③ 方法干货(2-3 点,主体):每点 = 一句结论 + 一句怎么做。
   用"第一/第二/第三"或"记住这3步"带出,每点 15-25 字说清。
   必须具体可操作,禁止空话("要重视/要选对方法")。

④ 行动号召(结尾 1-2 句):软转化,不硬广。
   示例:"评论区扣'考研',我把时间表发你""关注我,下期讲择校避坑"。
   禁止"快来报名,限时优惠"式叫卖。

【语言节奏 — 防划走】
- 口语化,像跟熟人聊天;书面语("此外/综上所述/值得注意的是")全删
- 短句为主,8-15 字一句,有停顿感,一句话一行
- 每 10-15 秒一个信息点或转折,拉回注意力
- 适当用数字、反问、情绪词,但不贩卖焦虑
- 整篇按口播节奏分段(钩子一段 / 痛点一段 / 方法几点 / 号召一段)"""


def build_script_prompt(
    *,
    style: dict[str, Any],
    org_profile: dict[str, Any],
    hotspots: list[dict[str, Any]],
    duration_sec: int = 60,
    platform: str = "短视频",
    extra_instruction: str = "",
) -> str:
    return f"""你是教培机构短视频内容主编,专写能留住人的口播稿。约{duration_sec}秒,{platform}。
必须服务本公司业务(勿写成无关个人号),遵守合规红线。

{_METHODOLOGY}

【风格 — 本机构主讲人设,方法论的个性化外壳】
{_style_block(style)}

【机构 — 内容必须围绕它】
{_org_block(org_profile)}

【热点/选题 — 从中选或结合】
{_hotspot_block(hotspots)}

【附加要求】
{extra_instruction or '无'}

【输出格式】
直接输出口播正文(钩子一行/痛点一行/方法各一行/号召一行),不要标题、不要"好的/以下是"等前缀、不要解释。""".strip()


def _default_chat_model() -> str:
    """默认聊天模型(registry), 替代开发残留的 mock-local——record/openai 下
    mock-local 的占位成本(0.999/1k)会打爆预算检查。"""
    try:
        from backend.core.model_registry import select_model_for_intent

        return select_model_for_intent("default").name
    except Exception:
        return "deepseek-v4-flash"


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
        from packages.harness import LLMHarness

        harness = LLMHarness()
        model_name = (model or "").strip() or _default_chat_model()
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
