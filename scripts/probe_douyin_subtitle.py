"""探针: 找 Tikhub 抖音 CC 字幕接口——试多个端点/字段位置。"""
import json
import os
import re

for line in open("config.env", encoding="utf-8"):
    m = re.match(r"\s*TIKHUB_API_KEY\s*=\s*(.+?)\s*$", line)
    if m:
        os.environ["TIKHUB_API_KEY"] = m.group(1)
        break

from packages.social.adapters.douyin import DouyinAdapter
from packages.social.http_client import TikHubHttpClient


def walk(obj, prefix="", hits=None, depth=0):
    """递归找 subtitle/caption 相关字段"""
    if hits is None:
        hits = []
    if depth > 5:
        return hits
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(s in kl for s in ("subtitle", "caption", "transcri", "lyric", "cla_info", "doodle_word", "watermark_audio")):
                hits.append(f"{prefix}{k} ({type(v).__name__}): {str(v)[:200]}")
            walk(v, f"{prefix}{k}.", hits, depth + 1)
    elif isinstance(obj, list) and obj:
        walk(obj[0], prefix + "[0].", hits, depth + 1)
    return hits


def main() -> None:
    client = TikHubHttpClient()
    adapter = DouyinAdapter()
    info = adapter.probe(client, "44465765782")
    items = adapter.fetch_recent(client, account_key="44465765782", external_id=info.external_id, limit=2)
    aweme_id = items[0].external_id
    print(f"aweme_id: {aweme_id}")

    for name, method, path, params in [
        ("web fetch_one_video", "get", "/douyin/web/fetch_one_video", {"aweme_id": aweme_id}),
        ("app/v3 fetch_one_video", "get", "/douyin/app/v3/fetch_one_video", {"aweme_id": aweme_id}),
    ]:
        print(f"\n=== {name} ===")
        try:
            payload = getattr(client, method)(path, params)
            hits = walk(payload)
            print(f"  subtitle/caption 相关字段 {len(hits)} 处:")
            for h in hits[:10]:
                print(f"  - {h}")
            if not hits:
                data = payload.get("data") or {}
                print("  无字幕字段。video keys:", sorted((data.get("video") or {}).keys())[:15])
            # 深挖 video 对象全部 keys(找字幕 URL)
            data = payload.get("data") or {}
            detail = data.get("aweme_detail") or data
            video = detail.get("video") or {}
            print("  video keys:", sorted(video.keys())[:20])
            for k in ("cla_info", "subtitle", "caption", "captions"):
                if video.get(k):
                    print(f"    video.{k}: {str(video[k])[:200]}")
        except Exception as e:
            print(f"  失败: {type(e).__name__}: {str(e)[:150]}")


if __name__ == "__main__":
    main()
