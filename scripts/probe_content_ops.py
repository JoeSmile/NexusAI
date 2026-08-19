"""探针: 热点 dig + 口播 generate 两条路复现。"""
import asyncio

from backend.core.content_ops.hotspot import dig_hotspots
from backend.core.content_ops.script_gen import generate_script
from backend.core.content_ops.style import resolve_style_for_generate


async def main() -> None:
    print("=== 路 1: 抓热点(topic_agent, 无画像) ===")
    try:
        r1 = dig_hotspots(
            adapter="topic_agent",
            categories=None,
            keywords="中考 政策",
            exclude_keywords=None,
            paste_text=None,
            org_profile={},
            industry=None,
            region=None,
            use_org_profile=True,
            user_note="",
        )
        print(f"OK count={r1.get('count')} 前3条: {[x.get('title') for x in (r1.get('items') or [])[:3]]}")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")

    print("=== 路 2: 口播生成(默认风格 + 热点) ===")
    try:
        from backend.database.pgvector_session import get_pg_session

        sf = get_pg_session()
        with sf.Session() as session:
            style = resolve_style_for_generate(session, "acme", None)
        print(f"style is_default={style.get('is_default')} creator_id={style.get('creator_id')}")
    except Exception as e:
        print(f"style FAIL: {type(e).__name__}: {e}")
        style = None

    hotspots = [
        {"title": "新学期家长最关心的三个入学问题", "summary": "入学适应、作息、家校沟通", "category": "K12", "score": 92},
        {"title": "中考政策变化", "summary": "2026 中考新政策解读", "category": "K12", "score": 90},
    ]
    try:
        out = await generate_script(
            tenant_id="acme",
            style=style or {},
            org_profile={},
            hotspots=hotspots,
            duration_sec=60,
            platform="douyin",
            extra_instruction="",
            student_names=[],
        )
        body = out.get("script") or out.get("content") or out
        print(f"OK script前120字: {str(body)[:120]}")
        print(f"keys: {list(out.keys())}")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
