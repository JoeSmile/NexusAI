"""探针: 捕获 LLM 调用,打印 prompt 构成/大小(content ops 链路)。"""
import asyncio

from packages.harness import LLMHarness

_orig_stream = LLMHarness.stream
_orig_generate = LLMHarness.generate


async def patched_stream(self, *a, **kw):
    model = kw.get("model") or (a[0] if a else "?")
    msgs = kw.get("messages") or (a[1] if len(a) > 1 else None)
    _dump("STREAM", model, msgs)
    async for tok in _orig_stream(self, *a, **kw):
        yield tok


async def patched_generate(self, *a, **kw):
    model = kw.get("model") or (a[0] if a else "?")
    msgs = kw.get("messages") or (a[1] if len(a) > 1 else None)
    _dump("GENERATE", model, msgs)
    return _orig_generate(self, *a, **kw)


def _dump(kind: str, model: str, msgs) -> None:
    print(f"\n===== {kind} model={model} =====")
    if not msgs:
        print("  (无 messages)")
        return
    total = sum(len(str(m.get("content", ""))) for m in msgs)
    print(f"  messages={len(msgs)} 总字符={total} ~tokens={total // 2}")
    for i, m in enumerate(msgs):
        c = str(m.get("content", ""))
        print(f"  [{i}] {m.get('role')} len={len(c)} head={c[:60]!r}...")
        if len(c) > 60:
            print(f"      tail={c[-80:]!r}")


LLMHarness.stream = patched_stream  # type: ignore[method-assign]
LLMHarness.generate = patched_generate  # type: ignore[method-assign]


async def main() -> None:
    from packages.content_ops.hotspot import dig_hotspots
    from packages.content_ops.script_gen import generate_script
    from packages.content_ops.style import resolve_style_for_generate
    from packages.database.pgvector_session import get_pg_session

    sf = get_pg_session()
    with sf.Session() as session:
        org = None
        try:
            from packages.content_ops.offerings import get_org_content_profile

            org = get_org_content_profile(session, "acme")
        except Exception:
            pass
        style = resolve_style_for_generate(session, "acme")

    print("\n--- 1) dig_hotspots(topic_agent) ---")
    dig = dig_hotspots(adapter="topic_agent", org_profile=org)
    print(f"dig count={dig.get('count')} (纯合成,应无 LLM 调用)")

    print("\n--- 2) generate_script(口播生成, LLM) ---")
    out = await generate_script(
        tenant_id="acme",
        style=style,
        org_profile=org,
        hotspots=dig.get("items") or [],
        duration_sec=60,
        platform="douyin",
    )
    print(f"script 生成完成, 长度={len(out.get('script') or '')}")


if __name__ == "__main__":
    asyncio.run(main())
