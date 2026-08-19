"""dashscope 文件上传 → 拿 URL → 提交真实转写 → 轮询。"""
import json
import os
import re
import time
import urllib.request

KEY = ""
for line in open("config.env", encoding="utf-8"):
    m = re.match(r"\s*QWEN_API_KEY\s*=\s*(.+?)\s*$", line)
    if m:
        KEY = m.group(1).strip()
        break

AUDIO = "/tmp/douyin_sample.wav"
URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"


def upload_file(path: str) -> str | None:
    """dashscope 文件上传接口(百炼文件管理)。"""
    import uuid

    boundary = uuid.uuid4().hex
    filename = os.path.basename(path)
    with open(path, "rb") as f:
        content = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        "https://dashscope.aliyuncs.com/api/v1/uploads",
        data=body,
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        print("上传响应:", json.dumps(data, ensure_ascii=False)[:300])
        # 找 URL
        return str(data.get("data", {}).get("upload_url") or data.get("url") or "")
    except urllib.error.HTTPError as e:
        print(f"上传失败 HTTP {e.code}: {e.read().decode()[:300]}")
        return None


def submit(url: str) -> dict:
    body = {
        "model": "qwen3-asr-flash-filetrans",
        "input": {"file_urls": [url]},
        "parameters": {"language_hints": ["zh"]},
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "X-DashScope-Async": "enable"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


if __name__ == "__main__":
    url = upload_file(AUDIO)
    if not url or url == "None":
        print("未拿到上传 URL,需要 OSS 或手动托管")
        raise SystemExit
    print("音频 URL:", url[:100])
    r = submit(url)
    print("转写任务:", json.dumps(r, ensure_ascii=False)[:300])
