# Batch 5a: 平行能力 — LangFuse + 缓存 + 安全护栏 + 文件上传 + 断路器

> **包含:** Task 05 (3 subtasks) + Task 06 (3 subtasks) + Task 09 (3 subtasks) + Task 10 (2 subtasks) + Task 11 (3 subtasks)  
> **预估:** 40-60 分钟  
> **依赖:** Batch 4（所有节点文件已存在，这里只是补全和增强）  
> **Commit:** `git add -A && git commit -m "feat: observability, cache, guardrails, file upload, circuit breaker\n\nSigned-off-by: Joe"`

---

## Task 05: LangFuse 可观测性

### 05.01: 客户端初始化

### 创建目录

```bash
mkdir -p backend/observability
touch backend/observability/__init__.py
```

### 创建: `backend/observability/langfuse_client.py`

```python
"""LangFuse 客户端 — 可观测性 SDK"""

import os
from langfuse import Langfuse

_lf: Langfuse | None = None


def get_langfuse() -> Langfuse | None:
    """获取 LangFuse 单例 — LangFuse 不可用时返回 None"""
    global _lf
    if _lf is not None:
        return _lf

    host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "pk-local-dev")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "sk-local-dev")

    # 如果配置了 LangFuse 才初始化
    if not public_key or public_key == "pk-local-dev":
        # dev mode — 不报错，静默降级
        return None

    try:
        _lf = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        return _lf
    except Exception:
        return None
```

---

### 05.02: 管线节点埋点

修改所有节点文件，在每个函数上加 `@observe()`：

**修改: `backend/pipeline/nodes/auth_check.py`**

```python
from langfuse.decorators import observe

@observe(name="pipeline.auth_check")
async def auth_check(state: PipelineState) -> PipelineState:
    ...
```

**修改: `backend/pipeline/nodes/analyze_parallel.py`**

```python
from langfuse.decorators import observe

@observe(name="pipeline.analyze_parallel")
async def analyze_parallel(state: PipelineState) -> PipelineState:
    ...
```

**修改: `backend/pipeline/nodes/llm_generate.py`**

```python
from langfuse.decorators import observe, langfuse_context

@observe(name="pipeline.llm_generate", as_type="generation")
async def llm_generate(state: PipelineState) -> PipelineState:
    ...
    # 记录 LLM generation 详细信息
    langfuse_context.update_current_generation(
        model=state["selected_model"],
        input=state["message"],
        output=state["response"],
        usage={"input": state.get("total_tokens", 0) // 2, "output": state.get("total_tokens", 0) // 2},
    )
    return state
```

分别在 `load_memory.py`, `rate_limiter.py`, `cache_check.py`, `guardrails_input.py`, `build_context.py`, `model_router.py`, `guardrails_output.py`, `write_memory.py` 加 `@observe()`。

> ⚠️ **Cursor 注意:** 只需在每个节点函数的 `async def` 上方加 `@observe(name="pipeline.<node_name>")`。不要在入口函数 `chat_pipeline` 上重复加（Batch 4 已经加了）。

---

### 05.03: 修改 router.py — LangFuse trace 名称

**修改: `backend/pipeline/router.py`**

```python
# 在 @observe 装饰器中添加 trace 名称
@router.post("/chat", response_model=ChatResponse)
@observe(name=f"chat_{tenant_id}/{session_id}")
async def chat_pipeline(...):
    # 注意：@observe 装饰器不能动态传参
    # 实际用固定名称
    ...
```

因为 `@observe()` 参数不能动态，用固定名 `"chat.pipeline"` 即可，Batch 4 的代码已经写对了。

---

## Task 06: 缓存系统

### 06.01: 精确缓存

**修改: `backend/pipeline/nodes/cache_check.py`** — 补全完整缓存逻辑

```python
"""缓存检查节点 — 精确 + 指纹缓存"""

import hashlib
import json
from sqlalchemy import text
from datetime import datetime, timedelta
from backend.database.pgvector_session import get_pg_session


def make_query_hash(message: str) -> str:
    """生成查询哈希（前 16 位）"""
    return hashlib.sha256(message.encode()).hexdigest()[:16]


async def cache_check(state: PipelineState) -> PipelineState:
    """检查精确缓存 + 指纹缓存"""
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    message = state["message"]

    query_hash = make_query_hash(message)

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        # 1. 精确缓存
        exact_key = f"exact:{tenant_id}:{user_id}:{query_hash}"
        exact = session.execute(
            text("SELECT value FROM cache_entries WHERE cache_key = :key AND expires_at > now()"),
            {"key": exact_key},
        ).fetchone()

        if exact:
            state["cache_hit"] = True
            state["cache_value"] = exact.value
            state["response"] = exact.value
            state["finish_reason"] = "cache_hit"
            from backend.core.metrics import cache_hits
            cache_hits.labels(tenant=tenant_id, cache_type="exact").inc()
            return state

        # 2. 指纹缓存
        fingerprint = state.get("fingerprint")
        if fingerprint:
            template_key = f"template:{fingerprint}"
            template = session.execute(
                text("SELECT value FROM cache_entries WHERE cache_key = :key AND expires_at > now()"),
                {"key": template_key},
            ).fetchone()
            if template:
                state["cache_hit"] = True
                state["cache_value"] = template.value
                state["response"] = template.value
                state["finish_reason"] = "cache_hit"
                from backend.core.metrics import cache_hits
                cache_hits.labels(tenant=tenant_id, cache_type="template").inc()
                return state

    from backend.core.metrics import cache_misses
    cache_misses.labels(tenant=tenant_id).inc()
    return state


def should_skip_to_end(state) -> str:
    return "end" if state.get("cache_hit") else "continue"


from backend.pipeline.state import PipelineState
```

---

### 06.02: 指纹缓存

### 创建: `backend/pipeline/cache/fingerprint_cache.py`

```python
"""意图指纹缓存 — 跨用户复用"""

import hashlib
import json
from sqlalchemy import text
from datetime import datetime, timedelta
from backend.database.pgvector_session import get_pg_session


def make_fingerprint(intent: str, entities: dict) -> str:
    """生成意图指纹"""
    normalized = {k: _normalize_entity(k, v) for k, v in entities.items()}
    sorted_str = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return f"{intent}:{hashlib.sha256(sorted_str.encode()).hexdigest()[:12]}"


def _normalize_entity(key: str, value: str) -> str:
    """标准化实体值"""
    # 地点归一化
    location_map = {
        "北京": "beijing", "上海": "shanghai", "广州": "guangzhou",
        "深圳": "shenzhen", "杭州": "hangzhou",
    }
    if isinstance(value, str) and value in location_map:
        return location_map[value]
    return value
```

---

### 06.03: 意图指纹生成接入

**修改: `backend/pipeline/nodes/analyze_parallel.py`**

在 `analyze_parallel` 函数末尾（赋值完 intent + entities 后）添加：

```python
    # 生成意图指纹（用于缓存）
    from backend.pipeline.cache.fingerprint_cache import make_fingerprint
    if state.get("intent") and state.get("entities"):
        state["fingerprint"] = make_fingerprint(
            state["intent"], state["entities"]
        )
```

---

## Task 09: 安全护栏

### 09.01: GuardResult 基类

### 创建目录

```bash
mkdir -p backend/core/guardrails
touch backend/core/guardrails/__init__.py
```

### 创建: `backend/core/guardrails/base.py`

```python
"""护栏结果基类"""

from dataclasses import dataclass


@dataclass
class GuardResult:
    """护栏检查结果"""
    action: str   # "pass" | "redacted" | "blocked"
    redacted_text: str
    reason: str
```

---

### 09.02: 输入护栏

### 创建: `backend/core/guardrails/pii_patterns.py`

```python
"""PII 脱敏模式"""

PII_PATTERNS = {
    "phone": r"1[3-9]\d{9}",
    "id_card": r"\d{17}[\dXx]",
    "bank_card": r"\d{16,19}",
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "ip_address": r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
}
```

### 创建: `backend/core/guardrails/injection_patterns.py`

```python
"""Prompt 注入检测模式"""

INJECTION_PATTERNS = [
    r"忽略(系统)?(提示|指令|设定)",
    r"你(现在|接下来)是",
    r"忘记(所有)?(之前|上面)的",
    r"system\s*:",
    r"你是一个(新|不同)的",
    r"扮演",
    r"假装你是",
    r"请忽略",
    r"忽略.*指令",
    r"忽略.*规则",
    r"你是.*模型",
    r"system_prompt",
    r"你不需要遵守",
]
```

### 创建: `backend/core/guardrails/input_guard.py`

```python
"""输入护栏 — Prompt 注入检测 + PII 脱敏"""

import re
from backend.core.guardrails.base import GuardResult
from backend.core.guardrails.injection_patterns import INJECTION_PATTERNS
from backend.core.guardrails.pii_patterns import PII_PATTERNS


async def check_input(message: str) -> GuardResult:
    """检查用户输入"""
    # 1. Prompt 注入检测
    for pattern in INJECTION_PATTERNS:
        matches = re.findall(pattern, message)
        if matches:
            return GuardResult(
                action="blocked",
                redacted_text=message,
                reason=f"injection:{pattern}",
            )

    # 2. PII 脱敏
    redacted = message
    for pii_type, pattern in PII_PATTERNS.items():
        redacted = re.sub(pattern, f"[REDACTED:{pii_type}]", redacted)

    if redacted != message:
        return GuardResult(
            action="redacted",
            redacted_text=redacted,
            reason="pii_found",
        )

    # 3. 长度限制
    if len(message) > 10000:
        return GuardResult(
            action="redacted",
            redacted_text=message[:10000],
            reason="length_exceeded",
        )

    return GuardResult(action="pass", redacted_text=message, reason="")
```

### 创建: `backend/core/guardrails/output_guard.py`

```python
"""输出护栏 — 长度截断 + 内容检测"""

from backend.core.guardrails.base import GuardResult

# 敏感输出模式
OUTPUT_BLOCK_PATTERNS = [
    "API密钥",
    "sk-",      # OpenAI API Key 前缀
    "SECRET_KEY",
    "PASSWORD",
    "token.*sk-",
]


async def check_output(response: str) -> GuardResult:
    """检查 LLM 输出"""
    # 1. 长度截断
    if len(response) > 4000:
        return GuardResult(
            action="truncated",
            redacted_text=response[:4000],
            reason="length_exceeded",
        )

    # 2. 敏感内容检测
    import re
    for pattern in OUTPUT_BLOCK_PATTERNS:
        if re.search(pattern, response, re.IGNORECASE):
            return GuardResult(
                action="blocked",
                redacted_text="[OUTPUT BLOCKED: 包含敏感内容]",
                reason=f"sensitive_content:{pattern}",
            )

    return GuardResult(action="pass", redacted_text=response, reason="")
```

---

### 09.03: 修改 guardrails_input 节点

**修改: `backend/pipeline/nodes/guardrails_input.py`**

```python
"""输入护栏节点 — 注入检测 + PII 脱敏"""

from backend.core.guardrails.input_guard import check_input
from backend.core.guardrails.output_guard import check_output
from backend.core.metrics import guardrails_blocked


async def guardrails_input(state: PipelineState) -> PipelineState:
    """输入安全检查"""
    result = await check_input(state["message"])

    if result.action == "blocked":
        state["prompt_injection_detected"] = True
        state["guardrails_passed"] = False
        state["response"] = "输入内容不符合安全规范，已被拦截。"
        state["finish_reason"] = "blocked"
        state["error_code"] = "GUARD_001"
        guardrails_blocked.labels(
            tenant=state["tenant_id"], guard="injection"
        ).inc()
        return state

    if result.action == "redacted":
        state["pii_redacted"] = True
        state["message"] = result.redacted_text
        guardrails_blocked.labels(
            tenant=state["tenant_id"], guard="pii"
        ).inc()

    state["guardrails_passed"] = True
    return state


async def guardrails_output(state: PipelineState) -> PipelineState:
    """输出安全检查"""
    result = await check_output(state.get("response", ""))

    if result.action == "blocked":
        state["response"] = result.redacted_text
        state["finish_reason"] = "blocked"
        state["error_code"] = "GUARD_003"
        return state

    if result.action == "truncated":
        state["response"] = result.redacted_text

    return state


from backend.pipeline.state import PipelineState
```

---

## Task 10: 文件上传加固

### 10.01: file_sanitizer.py

### 创建: `backend/core/file_sanitizer.py`

```python
"""文件上传安全加固 — MIME 校验 + UUID 重命名"""

import uuid
import os
import re
from pathlib import Path

# 允许的 MIME 类型
ALLOWED_MIME = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/gif": b"GIF89a",
    "application/pdf": b"%PDF",
    "text/plain": None,  # 无固定 magic bytes
}

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".pdf", ".txt"}

# 最大文件大小 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024


def detect_mime(content: bytes) -> str | None:
    """通过文件头检测真实 MIME 类型"""
    for mime_type, magic in ALLOWED_MIME.items():
        if magic and content.startswith(magic):
            return mime_type
    return None


def validate_file(filename: str, content: bytes, content_type: str) -> tuple[bool, str]:
    """验证文件 — (通过, 错误信息)"""
    # 1. 大小检查
    if len(content) > MAX_FILE_SIZE:
        return False, "FILE_001: 文件超过 10MB 限制"

    # 2. 扩展名检查
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"FILE_002: 不允许的文件类型 {ext}"

    # 3. MIME 检测（读文件头，不信任 Content-Type）
    if ext != ".txt":  # txt 无固定 magic bytes
        real_mime = detect_mime(content)
        if real_mime is None:
            return False, "FILE_002: 无法识别文件类型"
        # 验证 Content-Type 不冲突（仅警告，不拒绝）
        if content_type and content_type.split(";")[0].strip() != real_mime:
            pass  # 只做检测不做强制

    return True, ""


def sanitize_filename(original: str) -> tuple[str, str]:
    """生成安全的存储文件名 — (存储名, 扩展名)"""
    ext = os.path.splitext(original)[1].lower()
    safe_name = f"{uuid.uuid4().hex}{ext}"
    return safe_name, ext


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)
```

---

### 10.02: 文件上传端点

### 创建: `backend/routers/files.py`

```python
"""文件上传接口 — 安全加固版"""

import os
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.core.file_sanitizer import (
    validate_file, sanitize_filename, UPLOAD_DIR, MAX_FILE_SIZE,
)
from backend.database.pgvector_session import get_pg_session

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """上传文件（安全加固）"""
    # 读取内容
    content = await file.read()
    content_type = file.content_type or ""

    # 验证文件
    valid, error_msg = validate_file(file.filename or "", content, content_type)
    if not valid:
        raise HTTPException(status_code=400, detail={"code": error_msg.split(":")[0], "message": error_msg})

    # 安全存储
    safe_name, ext = sanitize_filename(file.filename or "upload")
    file_path = UPLOAD_DIR / safe_name

    with open(file_path, "wb") as f:
        f.write(content)

    # 记录到数据库
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            INSERT INTO cache_entries (cache_key, cache_type, tenant_id, value, ttl_seconds, expires_at)
            VALUES (:key, 'file', :tid, :path, 86400, now() + interval '24 hours')
            RETURNING id
        """)
        row = session.execute(sql, {
            "key": f"file:{safe_name}",
            "tid": tenant.tenant_id,
            "path": str(file_path),
        }).fetchone()
        session.commit()

    return {
        "file_id": safe_name,
        "original_name": file.filename,
        "size": len(content),
        "content_type": content_type,
    }


@router.get("/{file_id}")
async def get_file(file_id: str):
    """获取上传文件"""
    # 防止路径穿越
    safe_name = os.path.basename(file_id)
    file_path = UPLOAD_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="file_not_found")
    return FileResponse(str(file_path))


# ⚠️ 不要挂载 StaticFiles 到 /uploads
# 所有文件通过 /api/files/{id} 访问
```

### 修改: `backend/app.py`

```python
# 移除以下行（如果存在）
# app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")

# 添加文件路由
from backend.routers.files import router as files_router
app.include_router(files_router)
```

---

## Task 11: 断路器 + 降级

> ⚠️ **注意:** Harness (Batch 5b) 自带断路器。这里提供一个独立版本，供非 Harness 场景使用。

### 11.01: CircuitBreaker

### 创建: `backend/core/circuit_breaker.py`

```python
"""断路器 — closed → (失败 N 次) → open → (超时) → half-open → (成功 1 次) → closed"""

import asyncio
import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class CircuitBreaker:
    """断路器"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    async def call(self, fn, fallback_fn=None):
        """执行被保护函数"""
        if self.state == CircuitState.OPEN:
            if fallback_fn:
                return await fallback_fn() if asyncio.iscoroutinefunction(fallback_fn) else fallback_fn()
            raise Exception(f"CircuitBreaker[{self.name}]: open")

        try:
            result = await fn() if asyncio.iscoroutinefunction(fn) else fn()
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            if fallback_fn:
                return await fallback_fn() if asyncio.iscoroutinefunction(fallback_fn) else fallback_fn()
            raise

    def _on_success(self):
        self._failure_count = 0
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED

    def _on_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
```

---

### 11.02: Fallback 回复

### 创建: `backend/core/fallback.py`

```python
"""降级回复"""

FALLBACK = {
    "zh": "系统暂时繁忙，请稍后再试。",
    "en": "Service temporarily unavailable. Please try again later.",
}


def get_fallback(lang: str = "zh") -> str:
    return FALLBACK.get(lang, FALLBACK["zh"])
```

---

### 11.03: 嵌入 llm_generate

**修改: `backend/pipeline/nodes/llm_generate.py`**

在文件开头添加：

```python
from backend.core.circuit_breaker import CircuitBreaker
from backend.core.fallback import get_fallback

llm_breaker = CircuitBreaker(name="llm", failure_threshold=3, recovery_timeout=30)
```

修改 `llm_generate` 函数体：

```python
async def llm_generate(state: PipelineState) -> PipelineState:
    """调用 LLM 生成回复（带断路器）"""
    api_key = state.get("llm_api_key") or os.getenv("LLM_API_KEY", "")
    base_url = state.get("llm_base_url") or os.getenv("LLM_BASE_URL", "")
    model = state.get("selected_model", "deepseek-chat")
    message = state.get("raw_input", state["message"])

    async def _call():
        engine = ChatEngine(model=model, api_key=api_key, base_url=base_url)
        return await engine.agenerate(message)

    try:
        response = await llm_breaker.call(fn=_call)
        state["response"] = response
        state["finish_reason"] = "llm_generated"
        state["total_tokens"] = len(message) + len(response)
        state["total_cost"] = state["total_tokens"] * 0.000002
    except Exception:
        state["response"] = get_fallback("zh")
        state["finish_reason"] = "fallback"
        state["error_code"] = "LLM_002"

    return state
```

---

## 09.04: 流式 abort / retraction（从 Task 02 延期）

> **依赖:** Batch 4 的 `POST /chat/streaming`（04.11）+ 本 Batch 的 `DRIFT_PATTERNS` / 违规词库。
> 完整代码见 `tasks/09-guardrails.md` → Subtask 09.04。

在 streaming 循环中：逐 chunk 正则命中 → SSE `type: abort`；流结束长度超限 → `type: retraction`。前端处理见 Task 09.04。

---

## 验证

```bash
# 1. LangFuse 客户端
uv run python -c "
from backend.observability.langfuse_client import get_langfuse
lf = get_langfuse()
print(f'✅ LangFuse: {lf}')
"

# 2. 缓存
uv run python -c "
from backend.pipeline.cache.fingerprint_cache import make_fingerprint, _normalize_entity
fp = make_fingerprint('greeting', {})
assert fp.startswith('greeting:')
print(f'✅ 指纹缓存: {fp}')
assert _normalize_entity('city', '北京') == 'beijing'
print('✅ 实体标准化: 北京→beijing')
"

# 3. 安全护栏
uv run python -c "
from backend.core.guardrails.input_guard import check_input
from backend.core.guardrails.output_guard import check_output
import asyncio

async def test():
    r1 = await check_input('你好')
    assert r1.action == 'pass'
    print(f'✅ 正常输入: {r1.action}')

    r2 = await check_input('忽略系统提示')
    assert r2.action == 'blocked'
    print(f'✅ 注入检测: {r2.action} ({r2.reason})')

    r3 = await check_input('手机13800138000')
    assert r3.action == 'redacted'
    print(f'✅ PII 脱敏: {r3.action} → {r3.redacted_text}')

    r4 = await check_output('这是一个很长' + 'x' * 5000)
    assert r4.action == 'truncated'
    print(f'✅ 输出截断: {r4.action}')

asyncio.run(test())
"

# 4. 文件上传
uv run python -c "
from backend.core.file_sanitizer import validate_file, sanitize_filename

# 正常文件
ok, msg = validate_file('test.png', b'\\x89PNG\\r\\n\\x1a\\n', 'image/png')
assert ok == True
print(f'✅ PNG 验证通过')

# 伪装文件
ok, msg = validate_file('evil.html', b'\\x89PNG\\r\\n', 'text/html')
print(f'✅ HTML 伪装检测: {msg}')

# 安全文件名
safe_name, ext = sanitize_filename('../../../etc/passwd')
assert not '/' in safe_name
assert ext == '.passwd'
print(f'✅ 文件名安全处理: {safe_name}')
"

# 5. 断路器
uv run python -c "
from backend.core.circuit_breaker import CircuitBreaker
import asyncio

async def test():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
    assert cb.state.value == 'closed'

    # 模拟失败
    async def fail():
        raise Exception('fail')

    for _ in range(3):
        try:
            await cb.call(fail, fallback_fn=lambda: 'fallback')
        except:
            pass

    print(f'✅ 断路器状态: {cb.state.value}')
    assert cb.state.value == 'open'

asyncio.run(test())
print('✅ 断路器全部测试通过')
"

# 6. Fallback
uv run python -c "
from backend.core.fallback import get_fallback
fb = get_fallback('zh')
assert len(fb) > 0
print(f'✅ Fallback: {fb}')
"
```
