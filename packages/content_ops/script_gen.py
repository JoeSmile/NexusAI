"""script.gen — style + org + hotspots →口播; G7 redaction on exit."""

from __future__ import annotations

import logging
import os
from typing import Any

from packages.memory.memory_service import redact_student_names_in_text

logger = logging.getLogger(__name__)


def is_llm_busy_fallback(text: str) -> bool:
    from packages.fallback import get_fallback

    body = (text or "").strip()
    if not body:
        return False
    busy = get_fallback("zh").strip()
    return body == busy or body.startswith(f"{busy}(")


def _default_chat_model() -> str:
    """Prefer env DEFAULT_MODEL / MODEL_* so local Ollama names win over registry leftovers."""
    for key in ("DEFAULT_MODEL", "MODEL_GOOD", "MODEL_BEST"):
        name = (os.getenv(key) or "").strip()
        if name:
            return name
    try:
        from packages.model_registry import select_model_for_intent

        return select_model_for_intent("content_creation").name
    except Exception:
        return "deepseek-v4-flash"


async def _resolve_script_model(tenant_id: str, model: str | None) -> str:
    requested = (model or "").strip()
    if requested:
        return requested
    try:
        from packages.llm_credentials import resolve_chat_model_for_request

        return await resolve_chat_model_for_request(tenant_id, None)
    except Exception:
        return _default_chat_model()


def _env_llm_credentials(model_name: str) -> tuple[str, str]:
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    base_url = os.getenv("LLM_BASE_URL") or ""
    try:
        from packages.model_registry import get_model

        spec = get_model(model_name)
        if spec is not None:
            if spec.api_key_ref:
                api_key = api_key or os.getenv(spec.api_key_ref) or ""
            base_url = spec.base_url or base_url
    except Exception:
        pass
    return api_key, base_url


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
    """热点/选题块: 标题 + 短摘要；snippet 做口语化清洗。"""
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


def load_top_templates(
    tenant_id: str, *, platform: str | None = None, limit: int = 3
) -> list[dict[str, Any]]:
    """加载租户沉淀的对标模板（SocialTemplate，sample_count 降序）。

    平台映射: SocialTemplate.platform 存 "douyin"/"xiaohongshu" 等英文码，
    script_gen 侧 platform 是中文"短视频"，v1 不精确匹配（按租户取高频即可），
    platform 参数保留做精确过滤的将来扩展。
    """
    try:
        from packages.database.pgvector_session import SocialTemplate
        from packages.database.session import get_pg_session
    except Exception:
        return []
    try:
        sf = get_pg_session()
        with sf.Session() as session:
            q = session.query(SocialTemplate).filter_by(tenant_id=tenant_id)
            if platform:
                q = q.filter(SocialTemplate.platform == platform)
            rows = (
                q.order_by(SocialTemplate.sample_count.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "template_type": r.template_type,
                    "template_key": r.template_key,
                    "sample_count": r.sample_count,
                    "structure_json": r.structure_json or {},
                }
                for r in rows
            ]
    except Exception:
        return []


def _template_block(templates: list[dict[str, Any]]) -> str:
    """对标模板块: 沉淀的爆款骨架（SocialTemplate 产物），按出现频次展示。

    输入元素: {template_type, sample_count, structure_json}
    structure_json.skeleton: {template_type, hook_slots[], outline_slots[]}
    """
    if not templates:
        return ""
    parts = []
    for i, t in enumerate(templates[:3], 1):
        n = int(t.get("sample_count") or 1)
        st = (t.get("structure_json") or {}).get("skeleton") or {}
        ttype = str(st.get("template_type") or t.get("template_type") or "generic")
        hook_slots = [str(x) for x in (st.get("hook_slots") or [])]
        outline_slots = [str(x) for x in (st.get("outline_slots") or [])]
        seq = " → ".join(
            [x for x in ([ttype] + hook_slots + outline_slots) if x and x != "empty"]
        )
        parts.append(f"模板{i}（对标{n}次出现）：{seq or 'generic'}")
    return "\n".join(parts)


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


def _brief_block(brief: dict[str, Any] | None) -> str:
    if not brief:
        return ""
    points = brief.get("key_points") or []
    if not isinstance(points, list):
        points = [points]
    lines = [
        "【素材简报】",
        f"选题：{brief.get('title') or ''} — {brief.get('summary') or ''}",
        f"背景：{brief.get('background') or ''}",
        "关键信息点：",
        *[f"- {p}" for p in points if p],
        f"风险：{'; '.join(str(x) for x in (brief.get('risks') or []) if x)}",
        "口播只用以上骨架，禁止编造无来源数字/政策条款/具体个人。",
    ]
    return "\n".join(lines)


def build_script_prompt(
    *,
    style: dict[str, Any],
    org_profile: dict[str, Any],
    hotspots: list[dict[str, Any]],
    duration_sec: int = 60,
    platform: str = "短视频",
    extra_instruction: str = "",
    brief: dict[str, Any] | None = None,
    templates: list[dict[str, Any]] | None = None,
) -> str:
    brief_part = _brief_block(brief)
    extra_brief = f"\n\n{brief_part}" if brief_part else ""
    template_part = _template_block(templates or [])
    template_brief = (
        f"\n\n【对标爆款结构 — 按这些高频骨架组织口播，不是内容来源】\n{template_part}"
        if template_part
        else ""
    )
    return f"""你是教培机构短视频内容主编,专写能留住人的口播稿。约{duration_sec}秒,{platform}。
必须服务本公司业务(勿写成无关个人号),遵守合规红线。

{_METHODOLOGY}

【风格 — 本机构主讲人设,方法论的个性化外壳】
{_style_block(style)}

【机构 — 内容必须围绕它】
{_org_block(org_profile)}

【热点/选题 — 从中选或结合】
{_hotspot_block(hotspots)}{extra_brief}{template_brief}

【附加要求】
{extra_instruction or '无'}

【输出格式】
直接输出口播正文(钩子一行/痛点一行/方法各一行/号召一行),不要标题、不要"好的/以下是"等前缀、不要解释。""".strip()


def _template_script(style: dict[str, Any], hotspots: list[dict[str, Any]] | None) -> str:
    title = (hotspots or [{}])[0].get("title") if hotspots else None
    opener = (style.get("sample_openers") or ["先问你一个问题……"])[0]
    return (
        f"{opener}\n"
        f"今天想聊的是：{title or '学习习惯'}。"
        f"结合我们机构的课程服务，给家长三个可立刻用的小方法。"
        f"记住：过程比一次分数更重要。感兴趣的话，评论区留言，我们下期细讲。"
    )


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
    brief: dict[str, Any] | None = None,
    templates: list[dict[str, Any]] | None = None,
    save: bool = False,
    owner_user_id: str = "",
    creator_id: str = "",
) -> dict[str, Any]:
    """LLM generate + 共用出口护栏 + 可选对标模板/落库。"""
    if templates is None:
        templates = load_top_templates(tenant_id, limit=3)
    prompt = build_script_prompt(
        style=style,
        org_profile=org_profile,
        hotspots=list(hotspots or []),
        duration_sec=duration_sec,
        platform=platform,
        extra_instruction=extra_instruction,
        brief=brief,
        templates=templates,
    )
    try:
        from packages.logging_config import get_logger

        get_logger(__name__).info(
            "script.gen context tenant=%s creator=%s style_keys=%s org_keys=%s "
            "hotspots=%s duration=%s extra=%s\nprompt:\n%s",
            tenant_id,
            creator_id or style.get("creator_id"),
            list((style or {}).keys()),
            list((org_profile or {}).keys()),
            [
                {"title": h.get("title"), "summary": (h.get("summary") or "")[:80]}
                for h in (hotspots or [])[:5]
            ],
            duration_sec,
            (extra_instruction or "")[:200],
            prompt,
        )
    except Exception:
        logger.debug("script.gen prompt log skipped", exc_info=True)
    text = ""
    llm_failed = False
    try:
        from packages.harness import LLMHarness

        harness = LLMHarness()
        model_name = await _resolve_script_model(tenant_id, model)
        api_key, base_url = ("", "")
        if model_name != "mock-local":
            api_key, base_url = _env_llm_credentials(model_name)
        chunks: list[str] = []
        async for token in harness.stream(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            tenant_id=tenant_id,
            api_key=api_key,
            base_url=base_url,
            max_tokens=1200,
        ):
            chunks.append(str(token))
        text = "".join(chunks).strip()
        if is_llm_busy_fallback(text):
            llm_failed = True
            logger.error("script.gen llm returned busy fallback model=%s", model_name)
            text = _template_script(style, hotspots)
    except Exception:
        logger.exception("script.gen llm failed; using template fallback")
        llm_failed = True
        text = _template_script(style, hotspots)

    redacted = False
    try:
        from packages.guardrails.generation_exit import sanitize_generation_exit

        result = await sanitize_generation_exit(
            text,
            tenant_id=tenant_id,
            names=student_names,
            warm=warm,
            apply_length_limit=False,
        )
        text = result.redacted_text
        redacted = "g7_student_pii" in (result.reason or "")
    except Exception:
        logger.debug("script.gen generation exit skipped", exc_info=True)
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

    payload: dict[str, Any] = {
        "script": text,
        "student_pii_redacted": redacted,
        "style_is_default": bool(style.get("is_default")),
        "prompt_chars": len(prompt),
        "llm_failed": llm_failed,
        "artifact_id": None,
    }
    if save and not llm_failed:
        from packages.content_ops.script_persist import persist_script_artifact
        from packages.database.pgvector_session import get_pg_session

        title = (hotspots[0].get("title") if hotspots else None) or "口播稿"
        sf = get_pg_session()
        with sf.Session() as session:
            payload["artifact_id"] = persist_script_artifact(
                session,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                creator_id=creator_id or str(style.get("creator_id") or "default"),
                title=str(title),
                body={k: v for k, v in payload.items() if k != "artifact_id"},
            )
            session.commit()
    return payload
