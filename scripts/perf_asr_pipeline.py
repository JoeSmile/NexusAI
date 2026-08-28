"""全路径计时: 分享链接 → 下载 → 抽音频 → ASR 转写 → 口播稿。"""
import json
import os
import re
import subprocess
import time
import uuid

import websocket

# --- 加载 key ---
TIKHUB_KEY = QWEN_KEY = ""
for line in open("config.env", encoding="utf-8"):
    m = re.match(r"\s*TIKHUB_API_KEY\s*=\s*(.+?)\s*$", line)
    if m:
        TIKHUB_KEY = m.group(1).strip()
        os.environ["TIKHUB_API_KEY"] = TIKHUB_KEY
    m = re.match(r"\s*QWEN_API_KEY\s*=\s*(.+?)\s*$", line)
    if m:
        QWEN_KEY = m.group(1).strip()
        os.environ["QWEN_API_KEY"] = QWEN_KEY

from packages.social.http_client import TikHubHttpClient

SHARE_URL = "https://v.douyin.com/osrxbNIzUho/"
WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
timings: dict[str, float] = {}


def mark(name: str) -> None:
    timings[name] = time.time() - timings["_t0"]
    print(f"  [{name}] {timings[name]:.2f}s")


def main() -> None:
    timings["_t0"] = time.time()

    # 1. 分享链接 → 视频数据(Tikhub by_share_url)
    print("1. 解析分享链接(Tikhub)...")
    client = TikHubHttpClient()
    payload = client.get("/douyin/web/fetch_one_video_by_share_url", {"share_url": SHARE_URL})
    detail = (payload.get("data") or {}).get("aweme_detail") or payload.get("data") or {}
    video = detail.get("video") or {}
    urls = (video.get("play_addr") or {}).get("url_list") or []
    mark("1_解析")

    # 2. 下载视频
    print("2. 下载视频...")
    import urllib.request

    req = urllib.request.Request(urls[0], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        blob = resp.read()
    with open("/tmp/perf_douyin.mp4", "wb") as f:
        f.write(blob)
    print(f"   下载 {len(blob)/1024/1024:.1f}MB")
    mark("2_下载")

    # 3. 抽音频
    print("3. 抽音频(ffmpeg)...")
    subprocess.run(
        ["ffmpeg", "-y", "-i", "/tmp/perf_douyin.mp4", "-vn", "-ar", "16000", "-ac", "1", "/tmp/perf_douyin.wav"],
        check=True, capture_output=True,
    )
    mark("3_抽音频")

    # 4. ASR 转写
    print("4. ASR 转写(paraformer-realtime-v2)...")
    ws = websocket.create_connection(
        WS_URL,
        header=[f"Authorization: Bearer {QWEN_KEY}"],
        timeout=180,
    )
    task_id = str(uuid.uuid4())
    ws.send(json.dumps({
        "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {
            "task_group": "audio", "task": "asr", "function": "recognition",
            "model": "paraformer-realtime-v2",
            "parameters": {"format": "pcm", "sample_rate": 16000, "language_hints": ["zh"]},
            "input": {},
        },
    }))
    while True:
        raw = ws.recv()
        if isinstance(raw, bytes):
            continue
        if "task-started" in str(raw):
            break
    with open("/tmp/perf_douyin.wav", "rb") as f:
        f.seek(44)
        data = f.read()
    step = len(data) // 40
    for i in range(0, len(data), step):
        ws.send_binary(data[i : i + step])
        time.sleep(0.05)
    ws.send(json.dumps({
        "header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {"input": {}},
    }))
    texts: list[str] = []
    while True:
        try:
            raw = ws.recv()
        except Exception:
            break
        if isinstance(raw, bytes):
            continue
        msg = json.loads(raw)
        sentence = ((msg.get("payload") or {}).get("output") or {}).get("sentence") or {}
        t = str(sentence.get("text") or "")
        if t:
            texts.append(t)
        if msg.get("header", {}).get("event") == "task-finished":
            break
    ws.close()
    full = max(texts, key=len) if texts else ""
    mark("4_ASR转写")

    print(f"\n===== 结果: {len(full)} 字 =====")
    print("各阶段耗时:")
    for k, v in timings.items():
        if k != "_t0":
            print(f"  {k}: {v:.2f}s")
    print(f"  总计: {time.time() - timings['_t0']:.2f}s")


if __name__ == "__main__":
    main()
