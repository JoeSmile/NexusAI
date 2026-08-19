"""探针: 验证抖音账号 44465765782 拉取后 content 是字幕全文还是简介。"""
import os
import re

# 加载 config.env 的 TIKHUB_API_KEY(后端启动时加载,探针手动)
for line in open("config.env", encoding="utf-8"):
    m = re.match(r"\s*TIKHUB_API_KEY\s*=\s*(.+?)\s*$", line)
    if m:
        os.environ["TIKHUB_API_KEY"] = m.group(1)
        break

from backend.core.social.adapters.douyin import DouyinAdapter
from backend.core.social.http_client import TikHubHttpClient


def main() -> None:
    client = TikHubHttpClient()
    adapter = DouyinAdapter()
    info = adapter.probe(client, "44465765782")
    print(f"账号: {info.nickname}  sec={info.external_id}")
    items = adapter.fetch_recent(client, account_key="44465765782", external_id=info.external_id, limit=8)
    print(f"列表接口拉到 {len(items)} 条\n")
    for i, it in enumerate(items, 1):
        content = it.content or ""
        src = it.content_source or "?"
        print(f"--- {i}. [{src}] len={len(content)} title={(it.title or '')[:30]}")
        print(f"    content前150: {content[:150]!r}")

    print("\n=== enrich(详情接口, desc<100 才调) ===")
    from backend.core.social.adapters.douyin import enrich_missing_content

    merged = enrich_missing_content(client, items, adapter=adapter)
    n_sub = sum(1 for c in merged if c.content_source == "subtitle")
    print(f"enrich 后: {len(merged)} 条, subtitle 条数={n_sub}")

    # 打印详情接口原始响应的 key 结构,找 subtitle/字幕相关字段
    print("\n=== 详情接口原始响应结构(subtitle 在哪) ===")
    payload = client.post_json(
        "/douyin/app/v3/fetch_multi_video_v2",
        [items[0].external_id],
    )
    details = (payload.get("data") or {}).get("aweme_details") or []
    if details:
        v = details[0]
        print("video keys:", sorted(v.keys())[:30])
        for k in ("subtitle", "desc", "caption"):
            val = v.get(k)
            if val:
                print(f"  {k}: {type(val).__name__} = {str(val)[:150]}")
            else:
                print(f"  {k}: 无")


if __name__ == "__main__":
    main()
