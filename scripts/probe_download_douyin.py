"""探针: 抖音分享链接 → Tikhub by_share_url → 下载视频(ASR 第一步)。"""
import os
import re

for line in open("config.env", encoding="utf-8"):
    m = re.match(r"\s*TIKHUB_API_KEY\s*=\s*(.+?)\s*$", line)
    if m:
        os.environ["TIKHUB_API_KEY"] = m.group(1)
        break

from backend.core.social.http_client import TikHubHttpClient

SHARE_URL = "https://v.douyin.com/osrxbNIzUho/"


def main() -> None:
    client = TikHubHttpClient()
    payload = client.get(
        "/douyin/web/fetch_one_video_by_share_url",
        {"share_url": SHARE_URL},
    )
    data = payload.get("data") or {}
    detail = data.get("aweme_detail") or data
    print("title:", str(detail.get("desc") or "")[:60])
    video = detail.get("video") or {}
    play = video.get("play_addr") or {}
    urls = play.get("url_list") or []
    print(f"play_addr urls: {len(urls)}")
    if not urls:
        print("keys:", sorted(video.keys()))
        return
    url = urls[0]
    print("下载 URL:", url[:90])
    # 下载
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        blob = resp.read()
    out = "/tmp/douyin_sample.mp4"
    with open(out, "wb") as f:
        f.write(blob)
    print(f"下载完成: {out} {len(blob)/1024/1024:.1f}MB")


if __name__ == "__main__":
    main()
