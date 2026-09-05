"""LLM structure analysis + replica (Task 52 S5) — harness only."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from packages.social.usage import COST_ANALYSIS_ITEM, COST_REPLICA, record_usage

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _default_model() -> str:
    try:
        from packages.model_registry import select_model_for_intent

        return select_model_for_intent("default").name
    except Exception:
        return "deepseek-v4-flash"


def run_coro(coro: Any) -> Any:
    """Run async harness from sync worker / tests."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _parse_json_obj(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(raw)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def stub_structure(content_text: str) -> dict[str, Any]:
    text = (content_text or "")[:500]
    return {
        "stub": True,
        "market": {},
        "close_reads": [],
        "golden_hook": "",
        "attraction": "",
        "storytelling": "",
        "logic": "",
        "template_type": "generic",
        "hooks": [],
        "outline": [],
        "topics": [],
        "replicables": [],
        "preview": text,
    }


async def analyze_structure(
    *,
    tenant_id: str,
    platform: str,
    title: str | None,
    content: str | None,
) -> dict[str, Any]:
    """Harness LLM → 口播结构拆解（给人看的段落，不是 schema 清单）。"""
    body = (content or "").strip()
    if len(body) < 20:
        return stub_structure(body)

    prompt = f"""你是顶级的短视频内容导演兼口播教练，不是语文老师。你的工作：把一条对标爆款稿**拆到骨子里**——让创作者不仅看懂结构，更看懂"这句话为什么能留住人、换个平庸说法会死在哪"。

输入是对标账号的完整口播文稿（逐字稿/字幕）。这是别人反复打磨过的作品，**每一句都有存在的理由**，你要做的就是把那些理由挖出来。

【拆解纪律 — 防止"小学生作文式"输出】
- **禁止**给段落贴标签就完事（"这段是痛点，引起共鸣"= 零分）。每段必须回答：它具体戳中什么心理？用了什么具体的语言机制（具体数字/场景细节/身份代入/反常识/损失厌恶/社会认同）？如果平庸地写会是什么样？
- **逐句而非逐段**：2 分钟稿 ≈ 300-500 字，挑出信息密度最高的 8-12 处关键句，逐句拆。每处都要问三遍：这句删了损失什么？为什么用这个词不用近义词？观众听到这秒的心理状态是什么？
- **不要复述**：原文已有的话不要转述一遍，直接给"它做了什么"。
- 你的分析本身也要像好文案——具体、有洞察、不空泛。宁可狠，不要温吞。

【市场维度 — 为什么这条能火】
在拆结构前，先判断这条稿在**吃哪个市场情绪**：焦虑贩卖？身份认同？信息差优越感？从众恐惧？痛点共情？还是纯娱乐？说清楚它瞄准的人群和他们的心理开关。

【对标基准 — 什么算"写得好"】
判断标准不是"对不对"，是"狠不狠"：这句话是不是像经典台词一样经得起反复琢磨？换个人能不能写出这句？如果 100 个同行都讲这话题，这句是不是让他们显得平庸的那句？

平台: {platform}
标题: {title or "（无）"}
口播文稿:
\"\"\"{body[:5000]}\"\"\"

只输出一个 JSON 对象，字段如下：
- market: 市场分析对象。{{"emotion": "这条稿在吃哪种市场情绪", "audience": "目标人群画像", "psychology": "人群的心理开关/痛点", "why_it_works": "为什么这选题这讲法能火"}}
- overview: 一段话概括整篇功能链（如「反常识钩子 → 身份代入痛点 → 3个方法点 → 软号召」），点出这条稿最值得学的 1 个地方（要具体到某句某手法，不要"结构清晰"这类废话）。
- segments: 数组，逐段拆解，每段: {{"quote": "原文关键句摘录", "role": "hook|pain|method|transition|cta|other", "analysis": "这段在结构里干什么+具体戳什么心理+用了什么语言机制+平庸写法会是什么样"}}
- close_reads: **逐句精读数组（本条的灵魂）**，挑 8-12 处最关键的句子，每项: {{"quote": "原句", "mechanism": "这句话具体用了什么机制（数字/场景/反常识/身份/损失厌恶/对比/设问…）", "psychology": "观众听到这秒的心理状态变化", "why_strong": "为什么这个词/这说法有力量，换平庸说法会损失什么", "craft": "创作者在这里的打磨痕迹（节奏/停顿/重复/押韵/留白…）"}}
- golden_hook: 黄金钩子。点出前 1-2 句原话，说明它为什么能停住拇指，给 1 个同类替换写法。
- attraction: 中段用了哪些承诺/冲突/利益/身份认同留人，每点带原句。
- storytelling: 场景/人物/转折/案例/对比怎么铺，观众代入点在哪，带原句。
- logic: 语言逻辑功能链（「钩子 → … → 收束」）+ 句式节奏（短句/排比/设问/停顿）。
- template_type: 利益直给|拦路式|清单式|趋势恐吓|疑问式|generic 之一（只给归类，不解释）。
- hooks: 短标签数组（钩子句式类型）。
- outline: 数组，每项 {{"role":"hook|pain|method|cta|other","text":"该段功能一句"}}。
- template_skeleton: 可复用骨架: {{"order": ["hook","pain","method","cta"], "per_section": {{"hook": "句式模板", "pain": "…", "method": "…"}}, "slots": ["可替换槽位"]}}。
- teaching: 教学要点数组，3-5 条，每条必须是"这条稿教的具体手法"，不是"要吸引观众"这类正确的废话。
- topics: 话题词数组。
- replicables: 可复用手法（一句一条，要具体到句式/机制级别）。
不要 markdown，不要 JSON 以外的字。"""

    try:
        from packages.harness import LLMHarness

        harness = LLMHarness()
        result = await harness.generate(
            model=_default_model(),
            messages=[{"role": "user", "content": prompt}],
            tenant_id=tenant_id,
            max_tokens=2200,
        )
        if not result.success:
            logger.warning("social analyze harness fail: %s", result.error)
            return stub_structure(body)
        parsed = _parse_json_obj(str(result.output or ""))
        if not parsed:
            return stub_structure(body)
        parsed["stub"] = False
        parsed.setdefault("market", {})
        parsed.setdefault("close_reads", [])
        parsed.setdefault("golden_hook", "")
        parsed.setdefault("attraction", "")
        parsed.setdefault("storytelling", "")
        parsed.setdefault("logic", "")
        parsed.setdefault("template_type", "generic")
        parsed.setdefault("hooks", [])
        parsed.setdefault("outline", [])
        parsed.setdefault("topics", [])
        parsed.setdefault("replicables", [])
        return parsed
    except Exception:
        logger.exception("social analyze_structure failed")
        return stub_structure(body)


async def generate_replica_from_template(
    *,
    tenant_id: str,
    platform: str,
    brand: dict[str, str],
    template_structure: dict[str, Any],
    source_title: str | None = None,
    source_preview: str | None = None,
) -> dict[str, Any]:
    """套品牌生成 titles×3 + script + tags。"""
    name = brand.get("name") or ""
    business = brand.get("business") or ""
    audience = brand.get("audience") or ""
    style = brand.get("style") or ""
    sample = template_structure.get("sample_structure") or template_structure
    skeleton = template_structure.get("skeleton") or {}

    prompt = f"""你是品牌短视频口播编剧。用「模版骨架」套入品牌信息,输出可直接拍的复刻稿。

【品牌】
机构名: {name}
业务: {business}
受众: {audience or "（未指定）"}
风格覆盖: {style or "（未指定,跟模版语气）"}

【模版骨架】
{json.dumps({"skeleton": skeleton, "sample": sample}, ensure_ascii=False)[:2500]}

【对标参考(勿照抄原文)】
标题: {source_title or "（无）"}
摘要: {(source_preview or "")[:400]}

只输出 JSON:
{{
  "titles": ["标题1","标题2","标题3"],
  "script": "口播正文,短句换行",
  "tags": ["标签1","标签2"]
}}
要求:标题含品牌或业务关键词;口播按 hook→pain→method→cta;不要markdown。"""

    try:
        from packages.harness import LLMHarness

        harness = LLMHarness()
        result = await harness.generate(
            model=_default_model(),
            messages=[{"role": "user", "content": prompt}],
            tenant_id=tenant_id,
            max_tokens=1200,
        )
        if result.success:
            parsed = _parse_json_obj(str(result.output or ""))
            if parsed and isinstance(parsed.get("titles"), list):
                titles = [str(t) for t in parsed["titles"][:3]]
                while len(titles) < 3:
                    titles.append(f"{name}：对标启发标题{len(titles) + 1}")
                return {
                    "stub": False,
                    "titles": titles,
                    "script": str(parsed.get("script") or ""),
                    "tags": [str(t) for t in (parsed.get("tags") or [])][:12],
                    "brand": brand,
                    "platform": platform,
                }
    except Exception:
        logger.exception("social replica harness failed")

    return {
        "stub": True,
        "titles": [
            f"{name}：{business or '对标'}启发一",
            f"{name}：{business or '对标'}启发二",
            f"{name}：{business or '对标'}启发三",
        ],
        "script": (
            f"你是不是也在为{business or '这件事'}发愁？\n"
            f"我们是{name}，今天用对标结构给你三点方法。\n"
            f"关注我，下期继续拆。"
        ),
        "tags": [t for t in [name, business] if t],
        "brand": brand,
        "platform": platform,
    }


def record_analysis_usage(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    platform: str,
) -> None:
    record_usage(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        platform=platform,
        operation="analysis",
        item_count=1,
        cost_usd=COST_ANALYSIS_ITEM,
    )


def record_replica_usage(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    platform: str,
) -> None:
    record_usage(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        platform=platform,
        operation="replica",
        item_count=1,
        cost_usd=COST_REPLICA,
    )
