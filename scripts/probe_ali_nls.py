"""阿里云 NLS 录音文件识别 v2: token → 提交任务 → 轮询。"""
import json
import os
import re
import time
import urllib.request

AK = SK = ""
for line in open(os.path.expanduser("~/.zshrc"), encoding="utf-8"):
    line = line.strip()
    m = re.match(r"(?:export\s+)?ali_role_accesskey_id\s*=\s*[\"']?([^\"'\s]+)", line)
    if m:
        AK = m.group(1)
    m = re.match(r"(?:export\s+)?ali_role_accesskey_secret\s*=\s*[\"']?([^\"'\s]+)", line)
    if m:
        SK = m.group(1)

APPKEY = "yDrJCTQuJpc2jXOb"
META = "https://nls-meta.cn-shanghai.aliyuncs.com"
GATEWAY = "https://nls-gateway.cn-shanghai.aliyuncs.com"


def post_json(url: str, body: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode()[:400]}


def get_token() -> str:
    url = f"{META}/rest/v1/token?AccessKeyId={AK}&AccessKeySecret={SK}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    tok = data.get("Token", {}).get("Id", "")
    print(f"token 获取: {'OK' if tok else 'FAIL'} {str(data)[:150]}")
    return tok


def submit_task(token: str, file_url: str) -> dict:
    url = f"{GATEWAY}/rest/v1/{APPKEY}/filetrans/tasks"
    return post_json(
        url,
        {"appkey": APPKEY, "file_link": file_url, "version": "4.0", "enable_words": True},
        {"X-NLS-Token": token},
    )


def get_result(token: str, task_id: str) -> dict:
    url = f"{GATEWAY}/rest/v1/{APPKEY}/filetrans/{task_id}"
    req = urllib.request.Request(url, headers={"X-NLS-Token": token})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


if __name__ == "__main__":
    tok = get_token()
    if not tok:
        raise SystemExit("token 失败")
    r = submit_task(tok, "https://example.com/audio.wav")
    print("提交任务:", json.dumps(r, ensure_ascii=False)[:300])
