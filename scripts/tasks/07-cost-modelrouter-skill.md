# Task 07: 成本治理 + 模型路由 + Skill 双路径

> 模型名从环境变量读，不是硬编码。
> Skill 自动扫描 `backend/skills/builtin/` 目录。
> **前置依赖:** `tasks/04-langgraph-pipeline.md`（需要 pipeline 节点）
> **完成后:** 无（独立 Task）

## Subtask 07.01: CostManager

**文件:** `backend/core/cost_manager.py`
- `check_budget(tenant_id, estimated_cost) -> bool`
- `record_consumption(tenant_id, cost, tokens)`
- 预算从 `tenant_config` 表读取

## Subtask 07.02: RateLimiter

**文件:** `backend/core/rate_limiter.py`
- 桶令牌: 每秒 10 请求/租户，突发 20
- 超出返回 `429 RateLimitExceeded`

## Subtask 07.03: BaseSkill + SkillResult + 二级权限 + 人工介入

**文件:** `backend/skills/base.py`

Skill 级别两层安全：
- **二级权限** — 除路由级 `chat:write` 外，个别 skill 需要额外权限（如 `tool:db_query`），执行前校验
- **人工介入** — 高风险操作（删数据、发邮件、超预算）先创建审批单，等 tenant_admin 通过才执行

```python
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any


@dataclass
class SkillResult:
    output: str
    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None          # AUTH_002 / PENDING_APPROVAL / 或其他错误码
    approval_request_id: str | None = None  # 需要审批时传回申请单号


class BaseSkill(ABC):
    id: str
    name: str
    description: str
    trigger_intents: list[str] = []
    tool_schema: dict = field(default_factory=dict)

    # ── 二级权限 ──────────────────────────────────────
    # 额外需要的权限，如 ["tool:db_query", "data:export"]
    required_permissions: list[str] = []

    # ── 人工介入 ──────────────────────────────────────
    requires_human_approval: bool = False   # 高风险操作需要审批
    approval_timeout: int = 3600            # 超时自动拒绝（秒）

    async def execute(
        self,
        entities: dict,
        tenant_id: str,
        user_context: dict | None = None,  # {tenant_id, user_id, permissions, role}
    ) -> SkillResult:
        """安全壳 + 实际执行"""
        perms = user_context.get("permissions", []) if user_context else []

        # 步骤 1: 二级权限校验
        if self.required_permissions:
            for perm in self.required_permissions:
                if not self._has_permission(perm, perms):
                    return SkillResult(
                        success=False,
                        error="AUTH_002",
                        output=f"需要权限: {perm}",
                    )

        # 步骤 2: 人工介入检查
        if self.requires_human_approval:
            request_id = await self._create_approval_request(
                tenant_id=tenant_id,
                user_id=user_context.get("user_id", "") if user_context else "",
                params=entities,
            )
            return SkillResult(
                success=False,
                error="PENDING_APPROVAL",
                output=f"该操作需要审批，申请单号: {request_id}",
                approval_request_id=request_id,
            )

        # 步骤 3: 实际执行
        return await self._do_execute(entities)

    @abstractmethod
    async def _do_execute(self, entities: dict) -> SkillResult:
        """子类实现具体逻辑"""
        ...

    def _has_permission(self, required: str, user_perms: list[str]) -> bool:
        """简单权限匹配，支持通配符 admin:*"""
        if "admin:*" in user_perms:
            return True
        for up in user_perms:
            if up.endswith(":*"):
                resource = up.split(":")[0]
                if required.startswith(resource):
                    return True
            if up == required:
                return True
        return False

    async def _create_approval_request(
        self,
        tenant_id: str,
        user_id: str,
        params: dict,
    ) -> str:
        """写入 approval_requests 表"""
        # TODO: INSERT INTO approval_requests (tenant_id, user_id, resource, action, params, status, timeout_at)
        return f"apr_{tenant_id}_{int(time.time())}"
```

## Subtask 07.04: SkillRegistry + 自动发现 + 权限传播

**文件:** `backend/skills/registry.py`

Registry 现在需要把 `user_context`（含 permissions）传入 `skill.execute()`，让二级权限和人工介入在 skill 内部校验。

```python
class SkillRegistry:
    def discover(self):
        """自动扫描 builtin/ 目录"""
        for importer, modname, _ in pkgutil.iter_modules(["backend/skills/builtin"]):
            module = importlib.import_module(f"backend.skills.builtin.{modname}")
            for attr in dir(module):
                cls = getattr(module, attr)
                if isinstance(cls, type) and issubclass(cls, BaseSkill) and cls is not BaseSkill:
                    self.register(cls())

    def get_skill_for_intent(self, intent: str, confidence: float, threshold=0.85):
        """获取匹配 skill（双路径短路径用）"""
        if confidence < threshold:
            return None
        skill_id = self._intent_map.get(intent)
        return self._skills.get(skill_id)

    async def execute_skill(
        self,
        skill_id: str,
        entities: dict,
        tenant_id: str,
        user_context: dict,  # {tenant_id, user_id, permissions, role}
    ) -> SkillResult:
        """带权限传播的 skill 执行"""
        skill = self._skills.get(skill_id)
        if not skill:
            return SkillResult(success=False, error="SKILL_NOT_FOUND")
        return await skill.execute(
            entities=entities,
            tenant_id=tenant_id,
            user_context=user_context,
        )
```

**二级权限校验链路：**

```text
model_router 节点
  └─ skill.execute(entities, tenant_id, user_context)
       ├─ required_permissions 非空 → 遍历校验 → 不通过返回 AUTH_002
       ├─ requires_human_approval=True → 创建 approval_request → 返回 PENDING_APPROVAL
       └─ 通过 → _do_execute()
```

**⚠️ Cursor 实现警告：**
- `execute()` 签名变了（加了 `user_context`），所有内置 skill 子类必须同步更新
- `_do_execute()` 是新的抽象方法，旧 `execute()` 实现要改名成 `_do_execute()`

## Subtask 07.05: 内置 Skill — emotion_response（兼容二级权限签名）

**文件:** `backend/skills/builtin/emotion_response.py`

> ⚠️ `execute()` 现在是 BaseSkill 的安全壳方法，子类必须实现 `_do_execute()`。

```python
class EmotionResponseSkill(BaseSkill):
    id = "emotion_response"
    name = "情绪回应"
    trigger_intents = ["emotion"]

    async def _do_execute(self, entities: dict) -> SkillResult:
        templates = {"焦虑": "听起来你有些焦虑...", "悲伤": "我理解你的感受..."}
        emotion = entities.get("emotion", "neutral")
        return SkillResult(output=templates.get(emotion, "我在听"), latency_ms=5)
```

## Subtask 07.06: model_router 节点

**文件:** `backend/pipeline/nodes/model_router.py`

model_router 现在从 `state` 获取 `user_context`（由上游 auth 节点注入），传给 skill 做二级权限 + 人工介入校验。

```python
ROUTING_RULES = {
    "greeting": {"model": os.getenv("MODEL_CHEAP", "deepseek-chat"), "max_tokens": 100},
    "emotion":  {"model": os.getenv("MODEL_CHEAP", "deepseek-chat"), "max_tokens": 200},
    "advice":   {"model": os.getenv("MODEL_GOOD", "deepseek-chat"), "max_tokens": 500},
    "default":  {"model": os.getenv("MODEL_BEST", "deepseek-chat"), "max_tokens": 1000},
}

async def model_router(state: PipelineState) -> PipelineState:
    skill = registry.get_skill_for_intent(state["intent"], state["intent_confidence"])
    if skill:
        # 带 user_context 执行 skill（含二级权限 + 人工介入校验）
        result = await registry.execute_skill(
            skill_id=skill.id,
            entities=state["entities"],
            tenant_id=state["tenant_id"],
            user_context=state.get("user_context", {}),
        )
        state["response"] = result.output
        state["finish_reason"] = "skill_executed" if result.success else result.error
        state["total_cost"] = 0.0
        # 人工介入待审批 — 将 approval_request_id 返回给前端轮询
        if result.error == "PENDING_APPROVAL":
            state["approval_request_id"] = result.approval_request_id
        return state  # 短路径，不走 LLM
    # 长路径
    state["selected_model"] = ROUTING_RULES.get(state["intent"], ROUTING_RULES["default"])["model"]
    return state
```

**⚠️ Cursor 实现警告：**
- `model_router` 现在需要 `state["user_context"]` — 上游 auth_check 节点必须注入这个字段
- 人工介入场景 `skill_executed` 不是真正的完成，前端需要轮询 `approval_request_id` 的状态
- 所有内置 skill 的 `execute()` 签名已改为 `(self, entities, tenant_id, user_context)`

## Subtask 07.07: Harness 通用调用 wrapper

> **核心思想：** LLM / Tool / Skill / MCP / Function 都是"调一个东西"——pre（预算/断路器/速率）+ execute（重试/超时）+ post（计时/LangFuse/成本/审计）这套逻辑完全一样。一个通用 `Harness.wrap()` 搞定，子类只扩展特定逻辑。

```
backend/core/harness/
├── __init__.py          # 导出 Harness, LLMHarness, HarnessResult
├── base.py              # Harness 基类 — 通用 pre/execute/post
└── llm.py               # LLMHarness(Harness) — 加 token 计数 + 成本计算
```

### 07.07a: 基类 `backend/core/harness/base.py`

```python
"""通用 Harness — 任何 callable 包进去自动可观测"""

from dataclasses import dataclass, field
import asyncio
import time
from collections.abc import Callable, Awaitable
from typing import Any


@dataclass
class HarnessResult:
    output: Any = None
    type: str = ""
    name: str = ""
    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None
    metadata: dict = field(default_factory=dict)


class Harness:
    """通用 wrapper — 断路器 + 重试退避 + 超时 + 计时 + 错误分类 + 审计"""

    def __init__(self):
        self._breaker_state = "closed"  # closed / open / half-open

    async def wrap(
        self,
        fn: Callable[[], Awaitable[Any]],
        *,
        type: str,             # "llm" | "tool" | "skill" | "mcp" | "function"
        name: str,             # 展示名，如 "weather_api" / "deepseek-chat"
        tenant_id: str,
        input: Any,            # 入参（用于 trace）
        metadata: dict | None = None,
    ) -> HarnessResult:
        meta = metadata or {}
        start = time.time()

        # ── pre ──────────────────────────────────────────
        if self._breaker_state == "open":
            return HarnessResult(
                output=meta.get("fallback", ""),
                type=type, name=name, success=False,
                error="breaker_open", metadata=meta,
            )

        # ── execute ──────────────────────────────────────
        try:
            output = await asyncio.wait_for(
                self._retry(fn),
                timeout=meta.get("timeout", 30),
            )
        except asyncio.TimeoutError:
            self._record_error(type, name, "timeout")
            return HarnessResult(
                output=meta.get("fallback", ""),
                type=type, name=name, success=False,
                error="timeout", latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            self._record_error(type, name, str(e))
            raise

        # ── post ─────────────────────────────────────────
        latency = (time.time() - start) * 1000
        self._record_metrics(type, name, latency)
        self._record_audit(tenant_id, type, name, input, output, latency)

        return HarnessResult(
            output=output, type=type, name=name,
            latency_ms=latency, success=True, metadata=meta,
        )

    async def _retry(self, fn: Callable[[], Awaitable[Any]]) -> Any:
        """3 次重试 + 指数退避"""
        last_exc = None
        for attempt in range(3):
            try:
                return await fn()
            except Exception as e:
                last_exc = e
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise last_exc  # type: ignore[misc]

    def _record_error(self, type: str, name: str, reason: str) -> None:
        # TODO: Prometheus error counter + log
        pass

    def _record_metrics(self, type: str, name: str, latency_ms: float) -> None:
        # TODO: Prometheus latency histogram
        pass

    def _record_audit(self, tenant_id: str, type: str, name: str,
                      input: Any, output: Any, latency_ms: float) -> None:
        # TODO: 审计日志入库
        pass
```

### 07.07b: LLM 子类 `backend/core/harness/llm.py`

只加 LLM 特有的逻辑（token 计数 + 成本 + LangFuse），调用走父类 `wrap()`：

```python
"""LLM Harness — Harness 子类，加 token / cost / LangFuse"""

from .base import Harness, HarnessResult


class LLMHarness(Harness):
    """LLM 调用入口 — 继承 wrap() 的重试/退避/断路器，加 token+cost"""

    async def generate(
        self,
        model: str,
        messages: list[dict],
        tenant_id: str,
        **kwargs,
    ) -> HarnessResult:
        # 1. 预算检查（LLM 独有）
        estimated = estimate_cost(model, kwargs.get("max_tokens", 1000))
        if not check_budget(tenant_id, estimated):
            raise ContextGateException("COST_001", "budget_exceeded")

        input_tokens = sum(count_tokens(m) for m in messages)

        # 2. 调父类 wrap()
        result = await self.wrap(
            fn=lambda: self._call_api(model, messages),
            type="llm",
            name=model,
            tenant_id=tenant_id,
            input=messages,
            metadata={
                "model": model,
                "input_tokens": input_tokens,
                "max_tokens": kwargs.get("max_tokens", 1000),
                "cost_per_token": COST_TABLE.get(model, 0),
            },
        )
        if not result.success:
            return result

        # 3. token + cost（LLM 独有）
        output_tokens = count_tokens(result.output)
        cost = calculate_cost(model, input_tokens + output_tokens)
        record_consumption(tenant_id, cost, output_tokens)

        # 4. LangFuse generation（LLM 独有）
        langfuse_context.update_current_generation(
            model=model,
            input=str(messages),
            output=result.output,
            usage={"input": input_tokens, "output": output_tokens},
        )

        result.metadata.update({
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
        })
        return result

    async def _call_api(self, model: str, messages: list[dict]) -> str:
        """底层 LLM API 调用"""
        client = try_create_chat_openai(model=model)
        resp = await client.ainvoke(messages)
        return resp.content
```

### 07.07c: 修改 `llm_generate` 节点

`backend/pipeline/nodes/llm_generate.py` 从自力更生变成只调 harness：

```python
from backend.core.harness import LLMHarness

harness = LLMHarness()

async def llm_generate(state: PipelineState) -> PipelineState:
    result = await harness.generate(
        model=state["selected_model"],
        messages=[{"role": "user", "content": state["message"]}],
        tenant_id=state["tenant_id"],
    )
    state["response"] = result.output
    state["total_tokens"] = result.metadata.get("input_tokens", 0) + result.metadata.get("output_tokens", 0)
    state["total_cost"] = result.metadata.get("cost", 0.0)
    state["pipeline_latency_ms"] = result.latency_ms
    return state
```

### 07.07d: Skill/Tool 也走同一 Harness

> Harness 在 `_do_execute()` 里调用（`execute()` 是 BaseSkill 的安全壳，已做权限+人工介入检查）。

```python
# backend/skills/builtin/emotion_response.py
from backend.core.harness import Harness

_harness = Harness()

class EmotionResponseSkill(BaseSkill):
    async def _do_execute(self, entities: dict) -> SkillResult:
        result = await _harness.wrap(
            fn=lambda: self._do_respond(entities),
            type="skill",
            name="emotion_response",
            tenant_id=...,   # 由模型调用方传入
            input=entities,
        )
        return SkillResult(output=result.output, latency_ms=result.latency_ms)
```

**两层安全的关系：**

```text
BaseSkill.execute()          ← 安全壳：二级权限 + 人工介入
  └─ _do_execute()           ← 实际逻辑
       └─ Harness.wrap()     ← 可观测壳：断路器 / 重试 / 计时 / 审计
```

### 07.07e: `LLMHarness.stream()`（从 Task 02 延期，供 04.11 SSE）

```python
# backend/core/harness/llm.py — 追加
async def stream(
    self, model, messages, tenant_id, **kwargs
) -> AsyncIterator[str]:
    """SSE streaming — 边吐 token 边追踪"""
    client = try_create_chat_openai(model=model)
    start = time.time()
    tokens: list[str] = []
    async for chunk in client.astream(messages):
        token = getattr(chunk, "content", None) or ""
        if not token:
            continue
        tokens.append(token)
        yield token

    latency = (time.time() - start) * 1000
    text = "".join(tokens)
    # 流完后记 cost / LangFuse（与 generate 对齐）
    record_consumption(tenant_id, calculate_cost(model, count_tokens(text)))
```

> 路由侧 `POST /chat/streaming` 见 **04.11**；流式 abort/retraction 见 **09.04**。

### 验证

```bash
# 基类
uv run python -c "
from backend.core.harness import Harness
h = Harness()
print('✅ Harness init ok')
print(f'  breaker state: {h._breaker_state}')
"

# LLM 子类
uv run python -c "
from backend.core.harness import LLMHarness
h = LLMHarness()
print('✅ LLMHarness init ok')
"
```

**关键变化总结：**

| 之前 | 之后 |
|------|------|
| `LLMHarness` 是独立类 | `Harness` 是基类，`LLMHarness(Harness)` 是子类 |
| 只给 LLM 用 | `Harness.wrap()` 通用，Skill/Tool/LLM 全部走同一管道 |
| 重试/断路器/预算写死在 LLMHarness | 重试/超时/断路器在基类 `wrap()` 里，子类只管 LLM 特有逻辑 |
| `llm_generate` 节点 20 行 | `llm_generate` 节点 10 行，只调 harness
## 验证

- 超限请求 → 429
- intent="emotion"+0.92 → 走 skill，不走 LLM
- 无 `tool:db_query` 权限的用户调用的 skill 含该权限 → AUTH_002
- `requires_human_approval=True` 的 skill → 返回 PENDING_APPROVAL + approval_request_id

## Subtask 07.08: API Key 管理 + 自动故障切换

> 两种 Key 都要管：
> **A) ContextGate API Key**（用户调 ContextGate 用）— 检测到被入侵或消费异常 → 立即停用
> **B) LLM Provider Key**（ContextGate 调 Deepseek/OpenAI 用）— 被限流或报错 → 自动切备用 key

### 07.08a: LLM Provider Key 管理 + 故障切换

**创建:** `backend/core/harness/key_manager.py`

```python
@dataclass
class ProviderKey:
    id: str
    provider: str            # "deepseek" | "openai"
    key_encrypted: str       # 加密存储
    is_active: bool = True
    priority: int = 0        # 越小越优先
    error_count: int = 0
    last_error: datetime | None = None
    rate_limit_reset: datetime | None = None


class LLMKeyManager:
    """多 Key 管理 — 自动故障切换 + 异常检测"""

    def __init__(self):
        self._keys: dict[str, list[ProviderKey]] = {}

    def get_active_key(self, model: str) -> ProviderKey:
        """获取当前可用 key，按优先级。异常时自动切下一个"""
        provider = model.split("/")[0]
        keys = sorted(self._keys.get(provider, []), key=lambda k: k.priority)
        for key in keys:
            if key.is_active and not self._is_rate_limited(key):
                return key
            if self._is_rate_limited(key):
                self._auto_rotate(key)
        raise ContextGateException("LLM_003", "no_available_key", "所有 Key 不可用")

    def report_error(self, key: ProviderKey, error: Exception):
        """连续 3 次错误 → 自动停用，切下个 key"""
        key.error_count += 1
        key.last_error = datetime.utcnow()
        if key.error_count >= 3:
            key.is_active = False
            log_audit(None, "__system__", "key_manager",
                      action="key.disabled", input=key.id,
                      output=f"连续 3 次错误，已自动停用")

    def report_anomaly(self, key_id: str, reason: str):
        """消费异常 → 立即停用"""
        for keys in self._keys.values():
            for k in keys:
                if k.id == key_id:
                    k.is_active = False
                    log_audit(None, "__system__", "key_manager",
                              action="key.disabled", input=key_id,
                              output=f"异常检测: {reason}")
                    return

    def _auto_rotate(self, key: ProviderKey):
        """限流时降级优先级，5 分钟后再试"""
        key.priority += 100
        asyncio.create_task(self._recover_key_after(key, delay=300))

    def _is_rate_limited(self, key: ProviderKey) -> bool:
        if key.rate_limit_reset and key.rate_limit_reset > datetime.utcnow():
            return True
        return False
```

### 07.08b: ContextGate API Key 异常检测

**修改:** `backend/core/auth/api_key_auth.py`

```python
# 在 verify_api_key 中增加异常检测
ANOMALY_RULES = {
    "token_spike": lambda stats: stats["tokens_5min"] > stats["tokens_1h_avg"] * 10,
    "off_hours": lambda stats: not (6 <= stats["hour"] <= 23),
    "multi_ip": lambda stats: stats["unique_ips_5min"] > 3,
}

async def verify_api_key(api_key: str = Security(APIKeyHeader(name="X-API-Key"))) -> TenantContext:
    key_hash = sha256(api_key)
    row = await db.fetch_one("SELECT * FROM api_keys WHERE key_hash=:hash AND is_active=true", ...)
    if not row:
        raise HTTPException(401, detail={"code": "AUTH_001"})

    # 异常检测
    if row.role not in ("super_admin", "auditor"):  # 管理员跳过检测
        stats = await get_key_usage_stats(row.id)
        for rule_name, check in ANOMALY_RULES.items():
            if check(stats):
                await key_manager.report_anomaly(row.id, rule_name)
                raise HTTPException(403, detail={"code": "AUTH_004", "message": "key_disabled_anomaly"})

    return TenantContext(...)
```

### 07.08c: 管理 API — LLM Provider Key

**修改:** `backend/routers/admin.py`

```
POST   /api/admin/llm-keys              → 添加 LLM Provider Key (加密存储)
GET    /api/admin/llm-keys               → 查看所有 Key（不暴露原始值）
DELETE /api/admin/llm-keys/{id}          → 移除 Key
POST   /api/admin/llm-keys/{id}/test     → 测试 Key 是否可用
```

**验证:**
```bash
# LLM Key 故障切换
# 1. 配置 2 个 Deepseek Key
# 2. 让第一个 Key 连续报错 3 次
# 3. 观察第二个 Key 被自动启用，请求不中断

# API Key 异常检测
# 1. 用一个 user key 在凌晨 3 点发起大量请求
# 2. 该 key 被自动停用
# 3. 再用该 key 请求 → 403 AUTH_004
```
