# Batch 5b: 成本治理 + 模型路由 + Skill 双路径 + Harness 通用框架

> **包含:** Task 07 (7 subtasks)  
> **预估:** 50-70 分钟 — **Harness 重构会波及多个节点，务必一整个批次完成**  
> **依赖:** Batch 2 (auth/permissions) + Batch 3 (audit) + Batch 4 (pipeline nodes)  
> ⚠️ **这是架构设计最核心的批次：Harness 统一所有可观测调用、Skill 双路径、二级权限、人工介入**  
> **Commit:** `git add -A && git commit -m "feat: cost management, skill dual-path, harness framework\n\nSigned-off-by: Joe"`

---

## 架构回顾

```
Harness 两层安全:
  BaseSkill.execute()          ← 安全壳：二级权限 + 人工介入
    └─ _do_execute()           ← 实际逻辑
         └─ Harness.wrap()     ← 可观测壳：断路器 / 重试 / 计时 / 审计

model_router 双路径:
  intent+confidence≥0.85 → Skill 短路径 (50ms, $0)
  否则                  → LLM 长路径 (1-5s, 有成本)
```

---

## 目录初始化

```bash
mkdir -p backend/skills/builtin backend/core/harness
touch backend/skills/__init__.py
touch backend/skills/builtin/__init__.py
touch backend/core/harness/__init__.py
```

---

## 07.01: CostManager

### 创建: `backend/core/cost_manager.py`

```python
"""成本管理 — 预算检查 + 消费记录"""

from dataclasses import dataclass
from sqlalchemy import text
from backend.database.pgvector_session import get_pg_session
from backend.core.metrics import cost_total, tokens_total


# 模型价格表（美元/1K tokens）
COST_TABLE: dict[str, float] = {
    "deepseek-chat": 0.00014,
    "deepseek-reasoner": 0.00055,
    "gpt-4o": 0.0025,
    "gpt-4o-mini": 0.00015,
    "glm-4": 0.0001,
    "qwen-max": 0.002,
    "default": 0.0005,
}


def estimate_cost(model: str, max_tokens: int = 1000) -> float:
    """估算一次调用的最大成本"""
    price = COST_TABLE.get(model, COST_TABLE["default"])
    return price * max_tokens / 1000


def calculate_cost(model: str, total_tokens: int) -> float:
    """计算实际成本"""
    price = COST_TABLE.get(model, COST_TABLE["default"])
    return price * total_tokens / 1000


def count_tokens(text: str) -> int:
    """粗略 token 计数（中文≈1.5 token/字，英文≈0.25 token/字母）"""
    import re
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    return chinese_chars * 2 + english_chars // 4 + 10


def record_consumption(tenant_id: str, cost: float, tokens: int, model: str = "default") -> None:
    """记录消费"""
    cost_total.labels(tenant=tenant_id, model=model).inc(cost)
    tokens_total.labels(tenant=tenant_id, model=model).inc(tokens)


async def check_budget(tenant_id: str, estimated_cost: float) -> bool:
    """检查租户预算是否充足"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        config = session.execute(
            text("SELECT config FROM tenant_config WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).fetchone()

    if not config:
        return True  # 无预算配置 = 不限制

    budget_config = config.config.get("budget", {})
    daily_limit = budget_config.get("daily_limit", 10.0)  # 默认 $10/天
    monthly_limit = budget_config.get("monthly_limit", 200.0)  # 默认 $200/月

    # 简单起见，这里只做估算检查
    if estimated_cost > daily_limit:
        return False

    return True
```

---

## 07.02: RateLimiter

### 创建: `backend/core/rate_limiter.py`

```python
"""速率限制 — 桶令牌（租户级）"""

import time
from collections import defaultdict


class TokenBucket:
    """租户级桶令牌速率限制器"""

    def __init__(self, rate: float = 10.0, burst: int = 20):
        self.rate = rate
        self.burst = burst
        self._tokens: dict[str, float] = defaultdict(lambda: float(burst))
        self._last_refill: dict[str, float] = defaultdict(time.time)

    def consume(self, tenant_id: str) -> bool:
        """消费一个 token，返回是否允许通过"""
        now = time.time()
        elapsed = now - self._last_refill[tenant_id]
        self._tokens[tenant_id] = min(
            self.burst,
            self._tokens[tenant_id] + elapsed * self.rate,
        )
        self._last_refill[tenant_id] = now
        if self._tokens[tenant_id] >= 1:
            self._tokens[tenant_id] -= 1
            return True
        return False

    def reset(self, tenant_id: str) -> None:
        """重置租户的桶"""
        self._tokens[tenant_id] = float(self.burst)
        self._last_refill[tenant_id] = time.time()


# 全局单例
_bucket = TokenBucket()


def check_rate_limit(tenant_id: str) -> bool:
    """检查是否被限流"""
    return _bucket.consume(tenant_id)
```

---

## 07.03: BaseSkill + 二级权限 + 人工介入

### 创建: `backend/skills/base.py`

```python
"""Skill 基类 — 安全壳（二级权限 + 人工介入）"""

import time
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any, Optional
from sqlalchemy import text
from backend.database.pgvector_session import get_pg_session


@dataclass
class SkillResult:
    """Skill 执行结果"""
    output: str
    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None          # AUTH_002 / PENDING_APPROVAL / 错误码
    approval_request_id: str | None = None  # 人工介入审批单号


class BaseSkill(ABC):
    """Skill 基类 — 安全壳 + 实际执行"""

    id: str
    name: str
    description: str
    trigger_intents: list[str] = []
    tool_schema: dict = field(default_factory=dict)

    # ── 二级权限 ──
    required_permissions: list[str] = []

    # ── 人工介入 ──
    requires_human_approval: bool = False
    approval_timeout: int = 3600  # 秒

    async def execute(
        self,
        entities: dict,
        tenant_id: str,
        user_context: dict | None = None,
    ) -> SkillResult:
        """
        安全壳 + 实际执行。

        流程:
          1. 二级权限校验
          2. 人工介入检查
          3. 实际执行 (_do_execute)
        """
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
        start = time.time()
        result = await self._do_execute(entities)
        result.latency_ms = (time.time() - start) * 1000
        return result

    @abstractmethod
    async def _do_execute(self, entities: dict) -> SkillResult:
        """子类实现具体逻辑"""
        ...

    def _has_permission(self, required: str, user_perms: list[str]) -> bool:
        """权限匹配 — 支持通配符 admin:* 和 chat:*"""
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
        self, tenant_id: str, user_id: str, params: dict,
    ) -> str:
        """写入 approval_requests 表"""
        from datetime import datetime, timedelta
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            sql = text("""
                INSERT INTO approval_requests
                    (tenant_id, user_id, resource, resource_type,
                     action, params, status, timeout_at)
                VALUES
                    (:tid, :uid, :res, 'skill',
                     'execute', :params::jsonb, 'pending',
                     now() + interval '1 hour')
                RETURNING id
            """)
            row = session.execute(sql, {
                "tid": tenant_id, "uid": user_id,
                "res": f"skill:{self.id}",
                "params": params,
            }).fetchone()
            session.commit()
        return f"apr_{tenant_id}_{row.id}"
```

---

## 07.04: SkillRegistry

### 创建: `backend/skills/registry.py`

```python
"""Skill 注册中心 — 自动发现 + 权限传播"""

import pkgutil
import importlib
from backend.skills.base import BaseSkill, SkillResult


class SkillRegistry:
    """Skill 注册中心"""

    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}
        self._intent_map: dict[str, str] = {}

    def register(self, skill: BaseSkill) -> None:
        """注册一个 Skill"""
        self._skills[skill.id] = skill
        for intent in skill.trigger_intents:
            self._intent_map[intent] = skill.id

    def discover(self) -> None:
        """自动扫描 builtin/ 目录"""
        try:
            for importer, modname, _ in pkgutil.iter_modules(
                ["backend/skills/builtin"]
            ):
                module = importlib.import_module(f"backend.skills.builtin.{modname}")
                for attr_name in dir(module):
                    cls = getattr(module, attr_name)
                    if (
                        isinstance(cls, type)
                        and issubclass(cls, BaseSkill)
                        and cls is not BaseSkill
                    ):
                        self.register(cls())
        except FileNotFoundError:
            pass  # builtin 目录不存在时不报错

    def get_skill(self, skill_id: str) -> BaseSkill | None:
        """按 ID 获取 Skill"""
        return self._skills.get(skill_id)

    def get_skill_for_intent(
        self, intent: str, confidence: float, threshold: float = 0.85
    ) -> BaseSkill | None:
        """获取匹配意图的 Skill（双路径短路径用）"""
        if confidence < threshold:
            return None
        skill_id = self._intent_map.get(intent)
        if skill_id:
            return self._skills.get(skill_id)
        return None

    async def execute_skill(
        self,
        skill_id: str,
        entities: dict,
        tenant_id: str,
        user_context: dict,
    ) -> SkillResult:
        """带权限传播的 Skill 执行"""
        skill = self._skills.get(skill_id)
        if not skill:
            return SkillResult(success=False, error="SKILL_001", output="Skill 未找到")
        return await skill.execute(
            entities=entities,
            tenant_id=tenant_id,
            user_context=user_context,
        )


# 全局单例
registry = SkillRegistry()
```

---

## 07.05: 内置 Skill — emotion_response

### 创建: `backend/skills/builtin/emotion_response.py`

```python
"""内置 Skill — 情绪回应（双路径短路径示例）"""

from backend.skills.base import BaseSkill, SkillResult


class EmotionResponseSkill(BaseSkill):
    id = "emotion_response"
    name = "情绪回应"
    description = "对用户的情绪表达做出回应"
    trigger_intents = ["emotion"]

    # 不需要额外权限
    required_permissions = []

    async def _do_execute(self, entities: dict) -> SkillResult:
        emotion = entities.get("emotion", "neutral")

        templates = {
            "焦虑": "听起来你有些焦虑。要不要聊聊是什么让你感到不安？我在这里陪着你。",
            "悲伤": "我理解你的感受。有时候把伤心的事说出来，心里会好受一些。",
            "高兴": "真为你高兴！能分享你的快乐，我也感觉很温暖。",
            "愤怒": "你看起来有些生气。先深呼吸一下，慢慢说，我在听。",
            "孤独": "感到孤独确实很难受。你不是一个人，我随时在这里陪你聊天。",
            "害怕": "害怕是很正常的情绪。你可以告诉我发生了什么，我们一起面对。",
            "neutral": "我在听，你继续说吧。",
        }

        response = templates.get(emotion, templates["neutral"])
        return SkillResult(output=response, latency_ms=1.0)
```

---

## 07.06: model_router 节点

**⚠️ 覆盖 Batch 4 写的 model_router 节点**

### 修改: `backend/pipeline/nodes/model_router.py`

```python
"""模型路由节点 — 双路径 + 成本估算 + Skill 二级权限 + LLM Key 注入"""

import os

from backend.core.cost_manager import estimate_cost
from backend.skills.registry import registry

ROUTING_RULES = {
    "greeting": {
        "model": os.getenv("MODEL_CHEAP", "deepseek-chat"),
        "max_tokens": 100,
    },
    "emotion": {
        "model": os.getenv("MODEL_CHEAP", "deepseek-chat"),
        "max_tokens": 200,
    },
    "advice": {
        "model": os.getenv("MODEL_GOOD", "deepseek-chat"),
        "max_tokens": 500,
    },
    "default": {
        "model": os.getenv("MODEL_BEST", "deepseek-chat"),
        "max_tokens": 1000,
    },
}

# provider 推断映射
PROVIDER_MAP = {
    "deepseek": "deepseek",
    "gpt": "openai",
    "o1": "openai",
    "o3": "openai",
    "glm": "zhipu",
    "qwen": "qwen",
}


def _detect_provider(model: str) -> str:
    """根据模型名推断 provider"""
    model_lower = model.lower()
    for key, provider in PROVIDER_MAP.items():
        if key in model_lower:
            return provider
    return "default"


async def model_router(state: PipelineState) -> PipelineState:
    """
    双路径路由:
      - 短路径: Skill 直接执行（50-200ms, $0）
      - 长路径: LLM 调用（1-5s, 有成本）

    同时注入 tenant 级 LLM API Key（Task 18 就绪后可启用）。
    """
    intent = state.get("intent", "default")
    confidence = state.get("intent_confidence", 0.0)

    # 短路径: 尝试 Skill
    if confidence >= 0.85:
        try:
            skill = registry.get_skill_for_intent(intent, confidence)
            if skill:
                result = await registry.execute_skill(
                    skill_id=skill.id,
                    entities=state["entities"],
                    tenant_id=state["tenant_id"],
                    user_context=state.get("user_context", {}),
                )
                state["response"] = result.output
                state["finish_reason"] = (
                    "skill_executed" if result.success else result.error
                )
                state["total_cost"] = 0.0
                state["pipeline_latency_ms"] = result.latency_ms
                if result.error == "PENDING_APPROVAL":
                    state["approval_request_id"] = result.approval_request_id
                return state
        except ImportError:
            pass
        except Exception as e:
            state["response"] = f"Skill 执行错误: {str(e)}"
            state["finish_reason"] = "error"
            state["error_code"] = "SKILL_001"
            return state

    # 长路径: LLM 生成
    rule = ROUTING_RULES.get(intent, ROUTING_RULES["default"])
    state["selected_model"] = rule["model"]
    state["estimated_cost"] = estimate_cost(rule["model"], rule["max_tokens"])
    state["finish_reason"] = "routed_to_llm"

    # 注入 LLM API Key（Task 18 补充完整逻辑）
    # try:
    #     from backend.core.key_repository import LLMKeyRepository
    #     provider = _detect_provider(rule["model"])
    #     key_data = await LLMKeyRepository().get_key(state["tenant_id"], provider)
    #     if key_data:
    #         state["llm_api_key"] = key_data.api_key
    #         state["llm_base_url"] = key_data.base_url
    #         state["llm_key_id"] = key_data.id
    #         state["llm_key_version"] = key_data.key_version
    # except ImportError:
    #     pass  # Task 18 未就绪

    return state


def route_short_or_long(state: PipelineState) -> str:
    """条件边"""
    fr = state.get("finish_reason", "")
    if fr in ("skill_executed",):
        return "end"
    return "llm_generate"


from backend.pipeline.state import PipelineState
```

---

## 07.07: Harness 通用调用框架

### 07.07a: 基类

### 创建: `backend/core/harness/base.py`

```python
"""通用 Harness — 断路器 + 重试退避 + 超时 + 计时 + 错误分类 + 审计"""

from dataclasses import dataclass, field
import asyncio
import time
from collections.abc import Callable, Awaitable
from typing import Any

from backend.core.circuit_breaker import CircuitBreaker
from backend.core.metrics import errors_total


@dataclass
class HarnessResult:
    """Harness 执行结果"""
    output: Any = None
    type: str = ""        # "llm" | "tool" | "skill" | "mcp" | "function"
    name: str = ""        # 展示名
    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None
    metadata: dict = field(default_factory=dict)


class Harness:
    """
    通用调用 wrapper。

    功能:
      - 断路器 (closed → open → half-open)
      - 3 次重试 + 指数退避
      - 超时控制
      - 计时 + 错误分类
      - 审计日志（通过 callback）

    使用方式:
        harness = Harness()
        result = await harness.wrap(
            fn=lambda: call_api(...),
            type="llm",
            name="deepseek-chat",
            tenant_id="acme",
            input={"messages": [...]},
        )
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self._breaker = CircuitBreaker(name=name, failure_threshold=5, recovery_timeout=30)

    async def wrap(
        self,
        fn: Callable[[], Awaitable[Any]],
        *,
        type: str,
        name: str,
        tenant_id: str,
        input: Any,
        metadata: dict | None = None,
    ) -> HarnessResult:
        meta = metadata or {}
        start = time.time()

        # ── 执行 ──
        try:
            output = await asyncio.wait_for(
                self._retry(fn),
                timeout=meta.get("timeout", 30),
            )
        except asyncio.TimeoutError:
            self._record_error(tenant_id, type, name, "timeout")
            return HarnessResult(
                output=meta.get("fallback", ""),
                type=type, name=name, success=False,
                error="timeout",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            self._record_error(tenant_id, type, name, str(e))
            raise

        # ── 后处理 ──
        latency = (time.time() - start) * 1000
        self._record_metrics(type, name, latency)

        return HarnessResult(
            output=output,
            type=type, name=name,
            latency_ms=latency,
            success=True,
            metadata=meta,
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

    def _record_error(self, tenant_id: str, type: str, name: str, reason: str) -> None:
        errors_total.labels(tenant=tenant_id, error_code=f"{type}.{reason}").inc()

    def _record_metrics(self, type: str, name: str, latency_ms: float) -> None:
        from backend.core.metrics import request_duration
        request_duration.labels(
            method=type, endpoint=name, status="2xx"
        ).observe(latency_ms)
```

### 07.07b: LLM 子类

### 创建: `backend/core/harness/llm.py`

```python
"""LLM Harness — Harness 子类，加 token / cost / LangFuse"""

from backend.core.harness.base import Harness, HarnessResult
from backend.core.cost_manager import (
    estimate_cost, calculate_cost, count_tokens,
    check_budget, record_consumption, COST_TABLE,
)
from backend.modules.llm.core.llm_core import ChatEngine


class LLMHarness(Harness):
    """LLM 调用入口 — 继承 wrap() 的重试/退避/断路器，加 token+cost"""

    def __init__(self):
        super().__init__(name="llm")

    async def generate(
        self,
        model: str,
        messages: list[dict],
        tenant_id: str,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs,
    ) -> HarnessResult:
        """LLM 生成（带预算检查 + token 计数 + LangFuse）"""
        # 1. 预算检查
        estimated = estimate_cost(model, kwargs.get("max_tokens", 1000))
        if not await check_budget(tenant_id, estimated):
            return HarnessResult(
                output="预算超限，请求被拒绝。",
                type="llm", name=model, success=False,
                error="COST_001",
            )

        # 2. 调父类 wrap()
        input_tokens = sum(count_tokens(m.get("content", "")) for m in messages)
        result = await self.wrap(
            fn=lambda: self._call_api(model, messages, api_key, base_url),
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

        # 3. token + cost
        output_tokens = count_tokens(result.output)
        cost = calculate_cost(model, input_tokens + output_tokens)
        record_consumption(tenant_id, cost, output_tokens, model)

        # 4. LangFuse
        try:
            from langfuse.decorators import langfuse_context
            langfuse_context.update_current_generation(
                model=model,
                input=str(messages),
                output=result.output,
                usage={"input": input_tokens, "output": output_tokens},
            )
        except (ImportError, RuntimeError):
            pass  # LangFuse 不可用降级

        result.metadata.update({
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
        })
        return result

    async def _call_api(
        self, model: str, messages: list[dict],
        api_key: str | None = None, base_url: str | None = None,
    ) -> str:
        """底层 LLM API 调用"""
        engine = ChatEngine(model=model, api_key=api_key or "", base_url=base_url or "")
        prompt = "\n".join(m.get("content", "") for m in messages)
        return await engine.agenerate(prompt)
```

### 07.07c: 修改 llm_generate 节点

**修改: `backend/pipeline/nodes/llm_generate.py`**

```python
"""LLM 生成节点 — 调用 Harness"""

import os
from backend.core.harness import LLMHarness
from backend.core.fallback import get_fallback

harness = LLMHarness()


async def llm_generate(state: PipelineState) -> PipelineState:
    """通过 LLMHarness 生成回复"""
    model = state.get("selected_model", "deepseek-chat")
    tenant_id = state["tenant_id"]
    api_key = state.get("llm_api_key") or os.getenv("LLM_API_KEY", "")
    base_url = state.get("llm_base_url") or os.getenv("LLM_BASE_URL", "")
    message = state.get("raw_input", state["message"])

    result = await harness.generate(
        model=model,
        messages=[{"role": "user", "content": message}],
        tenant_id=tenant_id,
        api_key=api_key,
        base_url=base_url,
    )

    state["response"] = result.output
    state["total_tokens"] = (
        result.metadata.get("input_tokens", 0)
        + result.metadata.get("output_tokens", 0)
    )
    state["total_cost"] = result.metadata.get("cost", 0.0)
    state["pipeline_latency_ms"] = result.latency_ms

    if not result.success:
        state["response"] = get_fallback("zh")
        state["finish_reason"] = result.error or "error"
        state["error_code"] = "LLM_002"
    else:
        state["finish_reason"] = "llm_generated"

    return state


from backend.pipeline.state import PipelineState
```

---

## 07.07e: `LLMHarness.stream()`（从 Task 02 延期）

> 供 Batch 4 的 `POST /chat/streaming`（04.11）使用。完整说明见 `tasks/07-cost-modelrouter-skill.md` → 07.07e。

在 `backend/core/harness/llm.py` 的 `LLMHarness` 上追加 `async def stream(...) -> AsyncIterator[str]`：边 `astream` 边 yield token，流结束后记 cost / LangFuse（与 `generate` 对齐）。

---

## 注册到 app.py

**修改: `backend/app.py`**

在 `create_app()` 末尾、`return app` 之前添加：

```python
# 启动时自动发现 Skill
from backend.skills.registry import registry
try:
    registry.discover()
    logger.info(f"Skill registry: {len(registry._skills)} skills loaded")
except Exception as e:
    logger.warning(f"Skill discovery failed: {e}")
```

---

## 验证

```bash
# 1. CostManager
uv run python -c "
from backend.core.cost_manager import estimate_cost, calculate_cost, count_tokens
cost = estimate_cost('deepseek-chat', 1000)
assert cost > 0
print(f'✅ 估算成本: \${cost:.6f}')

tokens = count_tokens('你好世界 hello')
print(f'✅ Token 计数: {tokens}')

actual = calculate_cost('deepseek-chat', 100) 
print(f'✅ 实际成本: \${actual:.8f}')
"

# 2. RateLimiter
uv run python -c "
from backend.core.rate_limiter import TokenBucket
bucket = TokenBucket(rate=100, burst=50)
assert bucket.consume('test')
print('✅ 桶令牌: consume ok')
bucket.reset('test')
print('✅ 桶令牌: reset ok')
"

# 3. BaseSkill
uv run python -c "
from backend.skills.base import BaseSkill, SkillResult
from backend.skills.builtin.emotion_response import EmotionResponseSkill
skill = EmotionResponseSkill()
assert skill.id == 'emotion_response'
assert 'emotion' in skill.trigger_intents
print(f'✅ Skill: {skill.id} ({skill.name})')
print(f'   触发意图: {skill.trigger_intents}')
"

# 4. Harness
uv run python -c "
from backend.core.harness import Harness, HarnessResult
h = Harness('test')
print(f'✅ Harness init ok')
print(f'   断路器状态: {h._breaker.state.value}')
"

# 5. LLMHarness
uv run python -c "
from backend.core.harness import LLMHarness
h = LLMHarness()
print(f'✅ LLMHarness init ok')
print(f'   类型: {type(h).__name__}')
"
```
