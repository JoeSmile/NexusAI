"""DashScope paraformer-realtime-v2 本地流式转写(官方协议)。"""
import json
import os
import re
import uuid

import websocket

KEY = ""
for line in open("config.env", encoding="utf-8"):
    m = re.match(r"\s*QWEN_API_KEY\s*=\s*(.+?)\s*$", line)
    if m:
        KEY = m.group(1).strip()
        break

AUDIO = "/tmp/douyin_sample.wav"
WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"


def main() -> None:
    task_id = str(uuid.uuid4())
    ws = websocket.create_connection(
        WS_URL,
        header=[f"Authorization: Bearer {KEY}"],
        timeout=180,
    )
    ws.send(json.dumps({
        "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {
            "task_group": "audio",
            "task": "asr",
            "function": "recognition",
            "model": "paraformer-realtime-v2",
            "parameters": {
                "format": "pcm",
                "sample_rate": 16000,
                "disfluency_removal_enabled": False,
                "language_hints": ["zh"],
            },
            "input": {},
        },
    }, ensure_ascii=False))

    # 等 task-started
    while True:
        raw = ws.recv()
        if isinstance(raw, bytes):
            continue
        msg = json.loads(raw)
        if msg.get("header", {}).get("event") == "task-started":
            break

    # 发音频(PCM,跳过 wav 头)
    CHUNK = 3200
    with open(AUDIO, "rb") as f:
        f.seek(44)
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            ws.send_binary(chunk)

    # finish-task
    ws.send(json.dumps({
        "header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {"input": {}},
    }, ensure_ascii=False))

    texts: list[str] = []
    while True:
        try:
            raw = ws.recv()
        except Exception:
            break
        if isinstance(raw, bytes):
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        event = msg.get("header", {}).get("event") or ""
        payload = msg.get("payload") or {}
        # result-generated 的 text 是累计全文,只保留最后一条
        sentence = (payload.get("output") or {}).get("sentence") or {}
        text = str(sentence.get("text") or "")
        if text:
            texts.append(text)
        if event == "task-finished":
            break
    ws.close()
    full = max(texts, key=len) if texts else ""  # 最长一条 = 累计全文
    print("===== 口播逐字稿 =====")
    print(full)
    print("===== 字数:", len(full), "=====")
    with open("/tmp/douyin_transcript.txt", "w", encoding="utf-8") as f:
        f.write(full)


if __name__ == "__main__":
    main()
