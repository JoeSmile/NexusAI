# Batch 4: 核心管线 — LangGraph Pipeline（最大批次！）

> **包含:** Task 04 (10 subtasks: State→节点→图组装→路由转接→老代码退役)  
> **预估:** 60-90 分钟 — **注意：这是整个项目中最大、最关键的一个批次**  
> **依赖:** Batch 1+2+3（pgvector 模型 + Auth + TenantContext + Audit）  
> ⚠️ **务必一鼓作气在一个 Cursor 对话中完成，否则节点之间签名不一致**  
> **Commit:** `git add -A && git commit -m "feat: LangGraph pipeline with 10 nodes\n\nSigned-off-by: Joe"`

---

## 架构回顾

```
管线图（LangGraph StateGraph）:

[START]
  └─ auth_check → load_memory → rate_limiter → cache_check
       ├─ [hit] ──► [END]  （缓存命中，直接返回）
       └─ [miss] ──► guardrails_input → analyze_parallel(并行)
            → build_context → model_router
              ├─ [short path] execute skill → [END]
              └─ [long path] llm_generate → guardrails_output
                   → write_memory + audit → [END]
```

## PipelineState（TypedDict，不是 Pydantic!）

```
tenant_id, user_id, session_id, user_context ← 来自 auth
message, raw_input                             ← 用户输入
hot_memory, warm_memory                        ← 记忆加载
emotion, emotion_intensity                     ← 情绪分析
intent, intent_confidence, entities            ← 意图分析
fingerprint, cache_hit, cache_value            ← 缓存
pii_redacted, prompt_injection_detected        ← 护栏
guardrails_passed                              ← 护栏结果
selected_model, estimated_cost                 ← 模型路由
llm_tools, response, finish_reason             ← 结果
approval_request_id                            ← 人工介入
trace_id, total_tokens, total_cost             ← 观测
pipeline_latency_ms, error_code                ← 运维
langfuse_span                                  ← LangFuse
```

---

## 目录初始化

```bash
mkdir -p backend/pipeline/nodes backend/pipeline/cache
touch backend/pipeline/__init__.py
touch backend/pipeline/nodes/__init__.py
touch backend/pipeline/cache/__init__.py
```

---

## 04.01: PipelineState 定义

### 创建: `backend/pipeline/state.py`

```python
"""
PipelineState — LangGraph 管线状态定义。

⚠️ 使用 TypedDict，不是 Pydantic BaseModel！
每个节点签名: (state: PipelineState) -> PipelineState
"""

from typing import TypedDict, Optional, Any


class PipelineState(TypedDict):
    # ── 身份 ──
    tenant_id: str
    user_id: str
    session_id: str
    user_context: dict  # {tenant_id, user_id, permissions, role}

    # ── 输入 ──
    message: str
    raw_input: str

    # ── 记忆 ──
    hot_memory: list[dict]
    warm_memory: dict[str, str]

    # ── 分析结果 ──
    emotion: Optional[str]
    emotion_intensity: float
    intent: Optional[str]
    intent_confidence: float
    entities: dict[str, str]

    # ── 缓存 ──
    fingerprint: Optional[str]
    cache_hit: bool
    cache_value: Optional[str]

    # ── 护栏 ──
    pii_redacted: bool
    prompt_injection_detected: bool
    guardrails_passed: bool

    # ── 路由 ──
    selected_model: str
    estimated_cost: float
    llm_tools: list[dict]

    # ── 结果 ──
    response: str
    finish_reason: str  # skill_executed | llm_generated | cache_hit | blocked
    approval_request_id: Optional[str]

    # ── 观测 ──
    trace_id: str
    total_tokens: int
    total_cost: float
    pipeline_latency_ms: float
    error_code: Optional[str]
    langfuse_span: Optional[Any]

    # ── 扩展 (Task 18 LLM Key) ──
    llm_api_key: Optional[str]
    llm_base_url: Optional[str]
    llm_key_id: Optional[str]
    llm_key_version: Optional[int]


def make_initial_state(
    tenant_id: str,
    user_id: str,
    session_id: str,
    message: str,
    user_context: dict | None = None,
    trace_id: str | None = None,
) -> PipelineState:
    """创建初始 PipelineState"""
    import uuid

    return {
        # 身份
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": session_id,
        "user_context": user_context or {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "permissions": [],
            "role": "",
        },
        # 输入
        "message": message,
        "raw_input": message,
        # 记忆（空待填充）
        "hot_memory": [],
        "warm_memory": {},
        # 分析（空待填充）
        "emotion": None,
        "emotion_intensity": 5.0,
        "intent": None,
        "intent_confidence": 0.0,
        "entities": {},
        # 缓存
        "fingerprint": None,
        "cache_hit": False,
        "cache_value": None,
        # 护栏
        "pii_redacted": False,
        "prompt_injection_detected": False,
        "guardrails_passed": True,
        # 路由
        "selected_model": "deepseek-chat",
        "estimated_cost": 0.0,
        "llm_tools": [],
        # 结果
        "response": "",
        "finish_reason": "",
        "approval_request_id": None,
        # 观测
        "trace_id": trace_id or f"tr_{uuid.uuid4().hex[:12]}",
        "total_tokens": 0,
        "total_cost": 0.0,
        "pipeline_latency_ms": 0.0,
        "error_code": None,
        "langfuse_span": None,
        # LLM Key
        "llm_api_key": None,
        "llm_base_url": None,
        "llm_key_id": None,
        "llm_key_version": None,
    }
```

---

## 04.02: 节点 — auth_check

### 创建: `backend/pipeline/nodes/auth_check.py`

```python
"""认证节点 — 注入 user_context"""


async def auth_check(state: PipelineState) -> PipelineState:
    """
    注入 user_context。

    实际认证在 FastAPI Depends(verify_api_key) 中完成，
    节点直接从 state 获取已认证的 user_context。
    """
    # 确保 user_context 存在
    if not state.get("user_context"):
        state["user_context"] = {
            "tenant_id": state["tenant_id"],
            "user_id": state["user_id"],
            "permissions": [],
            "role": "",
        }
    return state


# 循环引用修复：在 state 导入之后再导入 PipelineState
from backend.pipeline.state import PipelineState
```

---

## 04.03: 节点 — load_memory + rate_limiter

### 创建: `backend/pipeline/nodes/load_memory.py`

```python
"""加载记忆节点 — 从 pgvector 加载 L1(热) + L2(温) 记忆"""

from backend.database.pgvector_session import get_pg_session
from sqlalchemy import text


async def load_memory(state: PipelineState) -> PipelineState:
    """加载用户记忆"""
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        # L1 热记忆：最近 5 条消息
        recent = session.execute(
            text("""
                SELECT role, content, emotion, created_at
                FROM chat_messages
                WHERE tenant_id = :tid AND user_id = :uid
                ORDER BY created_at DESC LIMIT 5
            """),
            {"tid": tenant_id, "uid": user_id},
        ).fetchall()

        # L2 温记忆：用户画像
        profile = session.execute(
            text("""
                SELECT key, value FROM user_memories
                WHERE tenant_id = :tid AND user_id = :uid
            """),
            {"tid": tenant_id, "uid": user_id},
        ).fetchall()

    state["hot_memory"] = [
        {"role": r.role, "content": r.content, "emotion": r.emotion}
        for r in reversed(recent)
    ]
    state["warm_memory"] = {p.key: p.value for p in profile}

    return state


from backend.pipeline.state import PipelineState
```

### 创建: `backend/pipeline/nodes/rate_limiter.py`

```python
"""速率限制节点 — 桶令牌检查"""

import time
from collections import defaultdict
from backend.core.errors import ContextGateException


class TokenBucket:
    """租户级桶令牌"""

    def __init__(self, rate: float = 10.0, burst: int = 20):
        self.rate = rate  # 每秒 token 数
        self.burst = burst  # 最大突发
        self.tokens: dict[str, float] = defaultdict(lambda: float(burst))
        self.last_refill: dict[str, float] = defaultdict(time.time)

    def consume(self, tenant_id: str) -> bool:
        now = time.time()
        elapsed = now - self.last_refill[tenant_id]
        self.tokens[tenant_id] = min(
            self.burst,
            self.tokens[tenant_id] + elapsed * self.rate,
        )
        self.last_refill[tenant_id] = now
        if self.tokens[tenant_id] >= 1:
            self.tokens[tenant_id] -= 1
            return True
        return False


_bucket = TokenBucket()


async def rate_limiter(state: PipelineState) -> PipelineState:
    """桶令牌检查 — 超出返回 429"""
    if not _bucket.consume(state["tenant_id"]):
        state["finish_reason"] = "rate_limited"
        state["error_code"] = "RATE_001"
        state["response"] = "请求过于频繁，请稍后再试。"
        raise ContextGateException("RATE_001", "rate_limited")
    return state


from backend.pipeline.state import PipelineState
```

---

## 04.04: 节点 — cache_check + guardrails_input

### 创建: `backend/pipeline/nodes/cache_check.py`

```python
"""缓存检查节点 — 精确 + 指纹缓存"""

import hashlib
from sqlalchemy import text
from backend.database.pgvector_session import get_pg_session


async def cache_check(state: PipelineState) -> PipelineState:
    """检查缓存命中"""
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    message = state["message"]

    # 精确缓存 key
    query_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
    exact_key = f"exact:{tenant_id}:{user_id}:{query_hash}"

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        # 精确缓存
        exact = session.execute(
            text("SELECT value FROM cache_entries WHERE cache_key = :key AND expires_at > now()"),
            {"key": exact_key},
        ).fetchone()

        if exact:
            state["cache_hit"] = True
            state["cache_value"] = exact.value
            state["response"] = exact.value
            state["finish_reason"] = "cache_hit"
            return state

    return state


from backend.pipeline.state import PipelineState


def should_skip_to_end(state: PipelineState) -> str:
    """条件边: 缓存命中 → END"""
    if state.get("cache_hit"):
        return "end"
    return "continue"
```

### 创建: `backend/pipeline/nodes/guardrails_input.py`

```python
"""输入护栏节点 — 占位，具体逻辑在 Batch 5a 补充"""


async def guardrails_input(state: PipelineState) -> PipelineState:
    """输入安全检查 — 占位节点"""
    # TODO(Batch 5a): 接入 Task 09 的完整护栏逻辑
    state["guardrails_passed"] = True
    return state


from backend.pipeline.state import PipelineState
```

---

## 04.05: 节点 — analyze_parallel

### 创建: `backend/pipeline/nodes/analyze_parallel.py`

```python
"""并行分析节点 — 情绪 + 意图 + 实体提取"""

import asyncio
import json
import os
from backend.modules.llm.core.llm_core import ChatEngine


async def analyze_parallel(state: PipelineState) -> PipelineState:
    """并发分析情绪和意图"""
    message = state["message"]

    emotion_task = _analyze_emotion(message)
    intent_task = _analyze_intent(message)

    emotion_result, intent_result = await asyncio.gather(
        emotion_task, intent_task, return_exceptions=True
    )

    # 处理情绪结果
    if isinstance(emotion_result, dict):
        state["emotion"] = emotion_result.get("emotion", "neutral")
        state["emotion_intensity"] = emotion_result.get("intensity", 5.0)
    else:
        state["emotion"] = "neutral"
        state["emotion_intensity"] = 5.0

    # 处理意图结果
    if isinstance(intent_result, dict):
        state["intent"] = intent_result.get("intent", "default")
        state["intent_confidence"] = intent_result.get("confidence", 0.0)
        state["entities"] = intent_result.get("entities", {})
    else:
        state["intent"] = "default"
        state["intent_confidence"] = 0.0
        state["entities"] = {}

    return state


async def _analyze_emotion(message: str) -> dict:
    """情绪分析 — mock 或真实 LLM"""
    mock = os.getenv("LLM_MOCK", "true").lower() == "true"
    if mock:
        emotions = {
            "焦虑": {"emotion": "焦虑", "intensity": 8},
            "伤心": {"emotion": "悲伤", "intensity": 7},
            "高兴": {"emotion": "高兴", "intensity": 6},
            "压力": {"emotion": "焦虑", "intensity": 8},
        }
        for keyword, result in emotions.items():
            if keyword in message:
                return result
        return {"emotion": "neutral", "intensity": 5.0}

    # 真实 LLM 调用
    engine = ChatEngine()
    prompt = f"分析以下消息的情绪(中文): {message}\n输出 JSON: {{\"emotion\": \"\", \"intensity\": 0-10}}"
    response = await engine.agenerate(prompt)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"emotion": "neutral", "intensity": 5.0}


async def _analyze_intent(message: str) -> dict:
    """意图分析 — mock 或真实 LLM"""
    mock = os.getenv("LLM_MOCK", "true").lower() == "true"
    if mock:
        greetings = ["你好", "嗨", "hello", "hi", "早上好", "晚上好"]
        emotions = ["焦虑", "伤心", "害怕", "紧张", "压力", "孤独"]
        advices = ["怎么办", "建议", "帮帮我", "有什么办法", "我该"]

        if any(g in message for g in greetings):
            return {"intent": "greeting", "confidence": 0.95, "entities": {}}
        if any(e in message for e in emotions):
            return {"intent": "emotion", "confidence": 0.9, "entities": {"emotion": message}}
        if any(a in message for a in advices):
            return {"intent": "advice", "confidence": 0.85, "entities": {"topic": message}}

        return {"intent": "default", "confidence": 0.5, "entities": {}}

    # 真实 LLM 调用
    engine = ChatEngine()
    prompt = (
        f"分析以下消息的意图(中文): {message}\n"
        f"输出 JSON: {{\"intent\": \"emotion|advice|greeting|default\", "
        f"\"confidence\": 0.0-1.0, \"entities\": {{}}}}"
    )
    response = await engine.agenerate(prompt)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"intent": "default", "confidence": 0.5, "entities": {}}


from backend.pipeline.state import PipelineState
```

---

## 04.06: 节点 — build_context + model_router

### 创建: `backend/pipeline/nodes/build_context.py`

```python
"""上下文组装节点"""


async def build_context(state: PipelineState) -> PipelineState:
    """组装最终上下文"""
    context_parts = []

    # 1. 用户画像
    if state["warm_memory"]:
        profile_str = "用户信息: " + ", ".join(
            f"{k}={v}" for k, v in state["warm_memory"].items()
        )
        context_parts.append(profile_str)

    # 2. 历史消息（最近 3 条）
    for msg in state["hot_memory"][-3:]:
        context_parts.append(f"{msg['role']}: {msg['content']}")

    # 3. 当前消息
    context_parts.append(f"user: {state['message']}")

    state["raw_input"] = "\n".join(context_parts)
    return state


from backend.pipeline.state import PipelineState
```

### 创建: `backend/pipeline/nodes/model_router.py`

```python
"""模型路由节点 — 双路径（短路径=Skill, 长路径=LLM）"""

import os

# 路由规则 — 模型名从环境变量读取
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


async def model_router(state: PipelineState) -> PipelineState:
    """
    双路径路由:
      - 短路径: intent+confidence >= 0.85 → 尝试执行 Skill
      - 长路径: → LLM 生成
    """
    intent = state.get("intent", "default")
    confidence = state.get("intent_confidence", 0.0)

    # 短路径: 尝试 Skill
    if confidence >= 0.85:
        try:
            from backend.skills.registry import registry

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
                if result.error == "PENDING_APPROVAL":
                    state["approval_request_id"] = result.approval_request_id
                return state
        except ImportError:
            pass  # Skill 模块未就绪，降级走 LLM

    # 长路径: LLM 生成
    rule = ROUTING_RULES.get(intent, ROUTING_RULES["default"])
    state["selected_model"] = rule["model"]
    state["estimated_cost"] = 0.001  # 估算值
    state["finish_reason"] = "routed_to_llm"

    return state


def route_short_or_long(state: PipelineState) -> str:
    """条件边: Skill 执行完 → END，否则 → llm_generate"""
    if state.get("finish_reason") in ("skill_executed",):
        return "end"
    return "llm_generate"


from backend.pipeline.state import PipelineState
```

---

## 04.07: 节点 — llm_generate + guardrails_output + write_memory

### 创建: `backend/pipeline/nodes/llm_generate.py`

```python
"""LLM 生成节点 — 调用大模型"""

import os
from backend.modules.llm.core.llm_core import ChatEngine


async def llm_generate(state: PipelineState) -> PipelineState:
    """调用 LLM 生成回复"""
    api_key = state.get("llm_api_key") or os.getenv("LLM_API_KEY", "")
    base_url = state.get("llm_base_url") or os.getenv("LLM_BASE_URL", "")

    engine = ChatEngine(
        model=state["selected_model"],
        api_key=api_key,
        base_url=base_url,
    )

    # 构建 prompt
    prompt = state.get("raw_input", state["message"])

    try:
        response = await engine.agenerate(prompt)
        state["response"] = response
        state["finish_reason"] = "llm_generated"
        # 粗略 token 估算
        state["total_tokens"] = len(prompt) + len(response)
        state["total_cost"] = state["total_tokens"] * 0.000002  # 粗略计算
    except Exception as e:
        state["response"] = "系统暂时繁忙，请稍后再试。"
        state["finish_reason"] = "error"
        state["error_code"] = "LLM_002"

    return state


from backend.pipeline.state import PipelineState
```

### 创建: `backend/pipeline/nodes/guardrails_output.py`

```python
"""输出护栏节点 — 占位"""


async def guardrails_output(state: PipelineState) -> PipelineState:
    """输出安全检查 — 占位，Batch 5a 补充"""
    # TODO(Batch 5a): 接入 Task 09 的完整输出护栏
    return state


from backend.pipeline.state import PipelineState
```

### 创建: `backend/pipeline/nodes/write_memory.py`

```python
"""写回记忆 + 缓存 + 审计"""

from datetime import datetime, timedelta
import hashlib
import os
from sqlalchemy import text
from backend.database.pgvector_session import get_pg_session, CacheEntry, ChatMessage
from backend.core.audit import log_audit


async def write_memory(state: PipelineState) -> PipelineState:
    """
    保存对话到 pgvector，写入缓存和审计日志。

    注意: 审计日志通过 FastAPI BackgroundTasks 异步写入，
    但在这个节点中我们直接同步写入到数据库。
    """
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    session_id = state["session_id"]
    message = state["message"]
    response = state["response"]
    trace_id = state["trace_id"]

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        # 1. 保存用户消息
        session.add(ChatMessage(
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=message,
            emotion=state.get("emotion"),
            emotion_intensity=state.get("emotion_intensity", 5.0),
        ))

        # 2. 保存回复
        session.add(ChatMessage(
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=response,
        ))

        # 3. 写入精确缓存
        mock = os.getenv("LLM_MOCK", "true").lower() == "true"
        if mock:
            query_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
            exact_key = f"exact:{tenant_id}:{user_id}:{query_hash}"
            session.add(CacheEntry(
                cache_key=exact_key,
                cache_type="exact",
                tenant_id=tenant_id,
                value=response,
                ttl_seconds=300,
                expires_at=datetime.utcnow() + timedelta(seconds=300),
            ))

        # 4. 写入审计日志
        audit_sql = text("""
            INSERT INTO audit_logs
                (tenant_id, user_id, action, trace_id,
                 input_text, output_text, model,
                 input_tokens, output_tokens, cost, latency_ms,
                 error_code)
            VALUES
                (:tid, :uid, 'chat', :trace_id,
                 :input, :output, :model,
                 :in_tok, :out_tok, :cost, :latency,
                 :err)
        """)
        session.execute(audit_sql, {
            "tid": tenant_id,
            "uid": user_id,
            "trace_id": trace_id,
            "input": message,
            "output": response,
            "model": state.get("selected_model", ""),
            "in_tok": len(message),
            "out_tok": len(response),
            "cost": state.get("total_cost", 0.0),
            "latency": state.get("pipeline_latency_ms", 0.0),
            "err": state.get("error_code"),
        })

        session.commit()

    return state


from backend.pipeline.state import PipelineState
```

---

## 04.08: 图组装 + 条件边

### 创建: `backend/pipeline/graph.py`

```python
"""LangGraph 图组装 — 编译完整管线"""

from langgraph.graph import StateGraph, END
from backend.pipeline.state import PipelineState

# 导入节点
from backend.pipeline.nodes.auth_check import auth_check
from backend.pipeline.nodes.load_memory import load_memory
from backend.pipeline.nodes.rate_limiter import rate_limiter
from backend.pipeline.nodes.cache_check import cache_check, should_skip_to_end
from backend.pipeline.nodes.guardrails_input import guardrails_input
from backend.pipeline.nodes.analyze_parallel import analyze_parallel
from backend.pipeline.nodes.build_context import build_context
from backend.pipeline.nodes.model_router import model_router, route_short_or_long
from backend.pipeline.nodes.llm_generate import llm_generate
from backend.pipeline.nodes.guardrails_output import guardrails_output
from backend.pipeline.nodes.write_memory import write_memory


def build_pipeline() -> StateGraph:
    """构建并编译 LangGraph 管线"""
    builder = StateGraph(PipelineState)

    # 注册所有节点
    builder.add_node("auth_check", auth_check)
    builder.add_node("load_memory", load_memory)
    builder.add_node("rate_limiter", rate_limiter)
    builder.add_node("cache_check", cache_check)
    builder.add_node("guardrails_input", guardrails_input)
    builder.add_node("analyze_parallel", analyze_parallel)
    builder.add_node("build_context", build_context)
    builder.add_node("model_router", model_router)
    builder.add_node("llm_generate", llm_generate)
    builder.add_node("guardrails_output", guardrails_output)
    builder.add_node("write_memory", write_memory)

    # 设置入口
    builder.set_entry_point("auth_check")

    # 线性顺序边
    builder.add_edge("auth_check", "load_memory")
    builder.add_edge("load_memory", "rate_limiter")
    builder.add_edge("rate_limiter", "cache_check")

    # 条件边: 缓存命中 → END
    builder.add_conditional_edges(
        "cache_check",
        should_skip_to_end,
        {
            "end": END,
            "continue": "guardrails_input",
        },
    )

    # 缓存未命中 → 护栏 → 分析 → 上下文
    builder.add_edge("guardrails_input", "analyze_parallel")
    builder.add_edge("analyze_parallel", "build_context")
    builder.add_edge("build_context", "model_router")

    # 条件边: Skill → END, LLM → llm_generate
    builder.add_conditional_edges(
        "model_router",
        route_short_or_long,
        {
            "end": END,
            "llm_generate": "llm_generate",
        },
    )

    # LLM → 输出护栏 → 写回记忆 → END
    builder.add_edge("llm_generate", "guardrails_output")
    builder.add_edge("guardrails_output", "write_memory")
    builder.add_edge("write_memory", END)

    return builder.compile()


# 编译单例
compiled_graph = build_pipeline()
```

---

## 04.09: FastAPI 转接层

### 创建: `backend/pipeline/router.py`

```python
"""FastAPI → LangGraph 转接层 — 管线入口"""

import time
from fastapi import APIRouter, Depends, BackgroundTasks, Request
from pydantic import BaseModel
from langfuse.decorators import observe

from backend.pipeline.state import make_initial_state
from backend.pipeline.graph import compiled_graph
from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.core.audit import log_audit

router = APIRouter(tags=["chat"])


# ── Schema ──
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    user_id: str = "anonymous"


class ChatResponse(BaseModel):
    response: str
    trace_id: str
    finish_reason: str
    total_tokens: int
    total_cost: float
    pipeline_latency_ms: float
    approval_request_id: str | None = None
    error_code: str | None = None


# ── 管线入口 ──

@router.post("/chat", response_model=ChatResponse)
@observe(name="chat.pipeline")
async def chat_pipeline(
    request: Request,
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    """处理聊天请求 — 走 LangGraph 管线"""
    start = time.time()

    # 创建初始状态
    initial = make_initial_state(
        tenant_id=tenant.tenant_id,
        user_id=body.user_id or tenant.user_id,
        session_id=body.session_id,
        message=body.message,
        user_context={
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "permissions": tenant.extra_permissions,
            "role": tenant.role,
        },
        trace_id=getattr(request.state, "trace_id", None),
    )

    # 执行管线
    try:
        final = await compiled_graph.ainvoke(initial)
        latency = (time.time() - start) * 1000
        final["pipeline_latency_ms"] = latency

        # 异步审计日志
        log_audit(
            background_tasks,
            tenant_id=final["tenant_id"],
            user_id=final["user_id"],
            action="chat",
            trace_id=final["trace_id"],
            input_text=final["message"],
            output_text=final["response"],
            model=final.get("selected_model", ""),
            input_tokens=len(final["message"]),
            output_tokens=len(final["response"]),
            cost=final.get("total_cost", 0.0),
            latency_ms=latency,
            error_code=final.get("error_code"),
            ip_address=request.client.host if request.client else "",
            user_agent=request.headers.get("User-Agent", ""),
        )

        return ChatResponse(
            response=final["response"],
            trace_id=final["trace_id"],
            finish_reason=final["finish_reason"],
            total_tokens=final["total_tokens"],
            total_cost=final["total_cost"],
            pipeline_latency_ms=latency,
            approval_request_id=final.get("approval_request_id"),
            error_code=final.get("error_code"),
        )

    except Exception as e:
        latency = (time.time() - start) * 1000
        return ChatResponse(
            response=f"系统错误: {str(e)}",
            trace_id=initial["trace_id"],
            finish_reason="error",
            total_tokens=0,
            total_cost=0.0,
            pipeline_latency_ms=latency,
            error_code="SYS_001",
        )
```

---

## 04.10: 老代码退役

在 `backend/services/chat_service.py` 等旧文件头部加 DEPRECATED 标记（不删文件）：

```python
# DEPRECATED: 请使用 backend/pipeline/router.py
# 新请求走 LangGraph 管线，此文件保留供参考
```

---

## 04.11: SSE Streaming 入口（从 Task 02 延期）

> **依赖:** 04.09；逐 token 需 **07.07e**；abort/retraction 需 **09.04**。本步只加路由骨架。
> 完整说明见 `tasks/04-langgraph-pipeline.md` → Subtask 04.11。

在 `backend/pipeline/router.py` 增加 `POST /chat/streaming`：
- 短路径（cache/skill/blocked）→ `JSONResponse`
- 长路径 → `StreamingResponse` + `llm_harness.stream(...)`（实现在 Batch 5b）

验证 curl 见 Task 04.11；若 07.07e 未合入，可先 stub 假 token 流打通协议。

---

## 注册到 app.py

### 修改: `backend/app.py`

```python
# 替换旧的 chat_router 导入
from backend.pipeline.router import router as chat_pipeline_router

# 注册管线路由（替换旧的 chat_router）
# ⚠️ 注释掉原来的 app.include_router(chat_router)
app.include_router(chat_pipeline_router)  # /chat 走 LangGraph
```

---

## 验证

```bash
# 1. 检查 PipelineState 类型
uv run python -c "
from backend.pipeline.state import PipelineState, make_initial_state
s = make_initial_state('tenant1', 'user1', 'sess1', '你好')
assert s['message'] == '你好'
assert s['tenant_id'] == 'tenant1'
assert s['cache_hit'] == False
print('✅ PipelineState 创建正确')
print(f'   state 有 {len(s)} 个字段')
"

# 2. 检查图编译
uv run python -c "
from backend.pipeline.graph import compiled_graph
print(f'✅ LangGraph 编译成功')
print(f'   节点数: {len(compiled_graph.nodes)}')
print(f'   边数: {len(compiled_graph.edges)}')
for name, node in compiled_graph.nodes.items():
    print(f'   - {name}')
"

# 3. 检查节点导入
uv run python -c "
from backend.pipeline.nodes.auth_check import auth_check
from backend.pipeline.nodes.load_memory import load_memory
from backend.pipeline.nodes.rate_limiter import rate_limiter
from backend.pipeline.nodes.cache_check import cache_check, should_skip_to_end
from backend.pipeline.nodes.analyze_parallel import analyze_parallel
from backend.pipeline.nodes.build_context import build_context
from backend.pipeline.nodes.model_router import model_router, route_short_or_long
from backend.pipeline.nodes.llm_generate import llm_generate
from backend.pipeline.nodes.write_memory import write_memory
print('✅ 全部 10 个节点导入成功')
"

# 4. 检查 FastAPI 路由
uv run python -c "
from backend.pipeline.router import router
print(f'✅ pipeline router 导入成功')
print(f'   路由: {[r.path for r in router.routes]}')
"
```
