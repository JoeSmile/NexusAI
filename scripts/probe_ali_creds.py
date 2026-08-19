"""阿里云 NLS 录音文件识别: 音频 → 转写(从 ~/.zshrc 读 AK/SK,不打印)。"""
import json
import os
import re
import time
import urllib.request

# 从 ~/.zshrc 提取 AK/SK(不打印值)
AK = SK = ""
for line in open(os.path.expanduser("~/.zshrc"), encoding="utf-8"):
    line = line.strip()
    m = re.match(r'(?:export\s+)?ali_role_accesskey_id\s*=\s*["\']?([^"\'\s]+)', line)
    if m:
        AK = m.group(1)
    m = re.match(r'(?:export\s+)?ali_role_accesskey_secret\s*=\s*["\']?([^"\'\s]+)', line)
    if m:
        SK = m.group(1)

print(f"AK/SK 读取: {'OK' if AK and SK else 'FAIL'} (len={len(AK)}/{len(SK)})")
if not AK or not SK:
    raise SystemExit("AK/SK 缺失")

# 阿里云 OpenAPI 签名(简单版,仅测试凭证有效性)
import hmac
import hashlib
import base64
from urllib.parse import quote

def sign(secret: str, string_to_sign: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()

# 用 STS GetCallerIdentity 验证凭证(轻量,免费)
params = {
    "AccessKeyId": AK,
    "Action": "GetCallerIdentity",
    "Format": "JSON",
    "SignatureMethod": "HMAC-SHA1",
    "SignatureNonce": str(int(time.time() * 1000)),
    "SignatureVersion": "1.0",
    "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "Version": "2015-04-01",
}
qs = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(params.items()))
string_to_sign = "GET&%2F&" + quote(qs, safe="")
params["Signature"] = sign(SK + "&", string_to_sign)
url = "https://sts.aliyuncs.com/?" + "&".join(
    f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in params.items()
)
try:
    with urllib.request.urlopen(url, timeout=15) as resp:
        body = json.loads(resp.read().decode())
    account = body.get("AccountId", "?")
    print(f"凭证有效 ✓ AccountId={account}")
except Exception as e:
    print(f"凭证验证失败: {str(e)[:200]}")
