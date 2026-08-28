"""LLM structure analysis + replica (Task 52 S5) — harness only."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from backend.core.social.usage import COST_ANALYSIS_ITEM, COST_REPLICA, record_usage

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _default_model() -> str:
    try:
        from backend.core.model_registry import select_model_for_intent

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

    prompt = f"""你是短视频口播教练,帮创作者「看懂一条稿子的结构,学会自己写」。输入是对标账号的完整口播文稿(逐字稿/字幕)。请做逐段、分层的结构拆解,既要展示结构,也要教用户这个结构是什么、为什么这么写、怎么改。

要求:
- **逐段覆盖**:原文每一段都要拆到(segments),不遗漏;每段摘录原文关键句(不 paraphrase)
- **分层讲**:先给整篇总链(overview),再逐段标功能(钩子/痛点/方法/过渡/号召),再讲段内技巧(句式/节奏/观众心理)
- **教学化**:每个结构点讲清楚"为什么这么写"——观众心理、停留逻辑、可替换写法;让用户看完能自己改稿
- 用中文写完整段落,结合原文具体句子,不要空泛形容词
- 不要复述全文,不要写「字段说明」,不要 markdown 标题
- 只输出一个 JSON 对象

平台: {platform}
标题: {title or "（无）"}
口播文稿:
\"\"\"{body[:5000]}\"\"\"

JSON 字段:
- overview: 一段话概括整篇功能链(如「反常识钩子 → 身份代入痛点 → 3个方法点 → 软号召」),点出这条稿最值得学的 1 个地方。
- segments: 数组,逐段拆解,每段: {{"quote": "原文关键句摘录", "role": "hook|pain|method|transition|cta|other", "analysis": "这段在结构里干什么、为什么这么写(观众心理)、可替换写法"}}
- golden_hook: 黄金钩子。点出前 1–2 句原话,说明它为什么能停住拇指(反差/数字/身份/威胁/提问等),以及起势节奏,给 1 个同类替换写法。
- attraction: 怎么吸引人。从开场到中段用了哪些承诺、冲突、利益或身份认同来留人,每点带原句。
- storytelling: 怎么讲故事。场景/人物/转折/案例/对比如何铺,观众代入点在哪,带原句。
- logic: 语言逻辑结构。写成「钩子 → … → 收束」的功能链,说明每段在说服上干什么,以及句式节奏(短句/排比/设问)。
- template_type: 利益直给|拦路式|清单式|趋势恐吓|疑问式|generic 之一(给模版归类,不要解释)
- hooks: 短标签数组(钩子句式类型,不要长原文)
- outline: 数组,每项 {{"role":"hook|pain|method|cta|other","text":"该段功能一句"}}
- template_skeleton: 可复用骨架(给后续抽模板用): {{"order": ["hook","pain","method","cta"], "per_section": {{"hook": "句式模板,如: 先问一个反常识问题+给出冲突答案", "pain": "…", "method": "…"}}, "slots": ["可替换槽位,如: 具体数字/人群身份/方法个数"]}}
- teaching: 教学要点数组,3-5 条:这条稿子教会你什么(新手最容易踩的坑、最值得模仿的手法)。
- topics: 话题词数组
- replicables: 可复用手法(一句一条)
不要 markdown,不要 JSON 以外的字。"""

    try:
        from packages.harness import LLMHarness

        harness = LLMHarness()
        result = await harness.generate(
            model=_default_model(),
            messages=[{"role": "user", "content": prompt}],
            tenant_id=tenant_id,
            max_tokens=1600,
        )
        if not result.success:
            logger.warning("social analyze harness fail: %s", result.error)
            return stub_structure(body)
        parsed = _parse_json_obj(str(result.output or ""))
        if not parsed:
            return stub_structure(body)
        parsed["stub"] = False
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
