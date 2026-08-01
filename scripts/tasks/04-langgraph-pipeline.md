# Task 04: LangGraph 管线重构

> ⚠️ **最大 Task，10 个 Subtask。**
> **前置依赖:** `tasks/02-auth-rbac.md`, `tasks/03-tenant-audit.md`
> **完成后:** `tasks/05-langfuse.md`, `tasks/06-cache.md`, `tasks/07-cost-modelrouter-skill.md` 可并行
> PipelineState 是 **TypedDict**，不是 Pydantic。
> 每个节点签名 `(state: PipelineState) -> PipelineState`。
> 并行用 `asyncio.gather`，不是 ThreadPool。
> FastAPI → LangGraph 通过 `pipeline/router.py` 转接。

## Subtask 04.01: PipelineState 定义

**文件:** `backend/pipeline/state.py`
```python
class PipelineState(TypedDict):
    tenant_id: str
    user_id: str
    session_id: str
    user_context: dict                     # {tenant_id, user_id, permissions, role} — 供二级权限校验
    message: str
    raw_input: str
    hot_memory: list[dict]
    warm_memory: dict[str, str]
    emotion: Optional[str]
    emotion_intensity: float
    intent: Optional[str]
    intent_confidence: float
    entities: dict[str, str]
    fingerprint: Optional[str]
    cache_hit: bool
    cache_value: Optional[str]
    pii_redacted: bool
    prompt_injection_detected: bool
    guardrails_passed: bool
    selected_model: str
    estimated_cost: float
    llm_tools: list[dict]
    response: str
    finish_reason: str  # skill_executed | llm_generated | cache_hit | blocked | AUTH_002 | PENDING_APPROVAL
    approval_request_id: Optional[str]    # 人工介入审批单号
    trace_id: str
    total_tokens: int
    total_cost: float
    pipeline_latency_ms: float
    error_code: Optional[str]
    langfuse_span: Optional[Any]
```

## Subtask 04.02: 节点 — auth_check（注入 user_context）

**文件:** `backend/pipeline/nodes/auth_check.py`
调用 Task 02 的 `verify_api_key`，将 tenant + permissions 注入 state 的 `user_context` 字段。

```python
from backend.core.auth.api_key_auth import verify_api_key

async def auth_check(state: PipelineState) -> PipelineState:
    # verify_api_key 是 FastAPI Depends，pipeline 内手动构造
    # 实际开发中由 router.py 的 Depends 预先校验，节点直接拿 tenant
    state["user_context"] = {
        "tenant_id": state["tenant_id"],
        "user_id": state["user_id"],
        "permissions": [],  # 由 Task 02 的 verify_api_key 填充
        "role": "",
    }
    return state
```

## Subtask 04.03: 节点 — load_memory + rate_limiter

**文件:**
- `backend/pipeline/nodes/load_memory.py` — 查 pgvector 加载 L1+L2
- `backend/pipeline/nodes/rate_limiter.py` — 桶令牌检查

## Subtask 04.04: 节点 — cache_check + guardrails_input

**文件:**
- `backend/pipeline/nodes/cache_check.py` — 精确+指纹缓存查询
- `backend/pipeline/nodes/guardrails_input.py` — 具体逻辑在 Task 09

## Subtask 04.05: 节点 — input_normalize + analyze_parallel

> 特殊符号归一化，提高 LLM 理解准确度。不是"识别用户情绪"，而是"消除符号噪声"。
> 放在 guardrails_input 之后、analyze_parallel 之前。

**创建:** `backend/pipeline/nodes/input_normalize.py`

```python
# Unicode 符号归一化映射
SYMBOL_MAP = {
    # emoji → 文字描述（消除 tokenizer 对不同 emoji 的理解差异）
    "😊": "[smile]", "😄": "[big_smile]", "🥰": "[heart_eyes]",
    "😭": "[cry]", "😢": "[sad]", "😡": "[anger]",
    "😤": "[frustrated]", "💔": "[heartbreak]",
    "👍": "[thumbs_up]", "🙄": "[roll_eyes]", "🤷": "[shrug]",
    # 全角 → 半角（消除编码不一致）
    "Ａ": "A", "Ｂ": "B", "，": ",", "。": ".", "！": "!", "？": "?",
    # 零宽字符（注入攻击常用载体）
    "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "",
}

async def input_normalize(state: PipelineState) -> PipelineState:
    """归一化输入中的特殊符号，减少 LLM 理解歧义"""
    text = state["message"]
    result = []
    for c in text:
        result.append(SYMBOL_MAP.get(c, c))
    state["message"] = "".join(result)
    state["normalized"] = text != state["message"]
    return state
```

**PipelineState 加字段:** `normalized: bool`（是否做了归一化）

**创建:** `backend/pipeline/nodes/analyze_parallel.py`
```python
async def analyze_parallel(state: PipelineState) -> PipelineState:
    emotion_task = _analyze_emotion(state["message"])
    intent_task = _analyze_intent(state["message"])
    emotion_result, intent_result = await asyncio.gather(emotion_task, intent_task)
    state["emotion"] = emotion_result.get("emotion")
    state["emotion_intensity"] = emotion_result.get("intensity", 5.0)
    state["intent"] = intent_result.get("intent")
    state["intent_confidence"] = intent_result.get("confidence", 0.0)
    state["entities"] = intent_result.get("entities", {})
    return state
```

## Subtask 04.06: 节点 — build_context + model_router

**文件:**
- `backend/pipeline/nodes/build_context.py` — 组装上下文，含角色锚定 + 强化插入
- `backend/pipeline/nodes/model_router.py` — 双路径（Task 07）

**build_context 三层角色保真 + 动态 prompt 调整:**

```python
# ── 基础角色 prompt ──
BASE_SYSTEM = "你是一个专业的情感支持助手..."

# ── 动态 prompt 构建 ──
def build_system_prompt(state: PipelineState) -> str:
    """
    根据用户状态动态调整系统 prompt。
    专业性保障（取代情绪注入）、温记忆偏好、租户配置。
    """
    parts = [BASE_SYSTEM]

    # 1. 专业性保障 — 根据对话上下文追加专业约束
    prof = inject_professionalism(state)
    if prof:
        parts.append(prof)

    # 2. 温记忆注入（用户偏好）
    warm = state.get("warm_memory", {})
    if warm.get("prefers_concise"):
        parts.append("\n该用户偏好简洁回答，请控制回复在 3 句以内。")
    if warm.get("language") == "en":
        parts.append("\nPlease respond in English.")

    # 3. 租户自定义指令
    tenant_config = state.get("tenant_config", {})
    if tenant_config.get("custom_prompt"):
        parts.append(f"\n{tenant_config['custom_prompt']}")

    return "\n".join(parts)


def inject_professionalism(state: PipelineState) -> str:
    """根据对话上下文追加专业性约束"""
    parts = []
    emotion = state.get("emotion")

    if emotion in ("extremely_sad", "angry", "crisis"):
        parts.append(
            "\n[专业性] 用户当前情绪较强，请保持共情但不过度介入。"
            "不要假装是真人，不要承诺做不到的事。"
        )
    if state.get("intent") == "advice":
        parts.append(
            "\n[专业性] 用户正在寻求建议，请确保回答基于可靠依据，"
            "并明确说明不能替代专业诊断或法律意见。"
        )
    return "\n".join(parts)


# ── 第二层：每轮重注入 + 强化间隔插入 ──
def build_messages(state: PipelineState) -> list[dict]:
    history = state.get("hot_memory", [])
    system_prompt = build_system_prompt(state)
    messages = [{"role": "system", "content": system_prompt}]

    for i, turn in enumerate(history):
        messages.append(turn)
        if i > 0 and i % 5 == 0:
            messages.append({
                "role": "system",
                "content": "记住你的角色不变，保持专业。"
            })

    messages.append({"role": "user", "content": state["message"]})

    # SYSTEM prompt 预留 token，永不截断
    reserved = count_tokens(system_prompt) + 500
    return truncate_from_left(messages, max_tokens - reserved)

# 第三层（输出漂移检测）在 guardrails_output 节点，见 Task 09.03
```

**PipelineState 加字段:** `tenant_config: dict`（从租户配置表读取）

## Subtask 04.07: 节点 — llm_generate + guardrails_output + write_memory（含记忆总结）

**文件:**
- `backend/pipeline/nodes/llm_generate.py` — LLM 调用
- `backend/pipeline/nodes/guardrails_output.py` — 输出审查
- `backend/pipeline/nodes/write_memory.py` — 写回记忆+缓存+审计+记忆总结

**write_memory 增加记忆总结:**

```python
# backend/pipeline/nodes/write_memory.py

SUMMARY_INTERVAL = 10  # 每 10 轮触发一次总结

async def write_memory(state: PipelineState) -> PipelineState:
    # 1. 写当前轮消息（原有）
    await store_message(state)

    # 2. 写审计日志（原有）
    # ...

    # 3. 检查是否需要触发记忆总结
    turn_count = await get_session_turn_count(state["session_id"])
    if turn_count > 0 and turn_count % SUMMARY_INTERVAL == 0:
        # 异步触发总结，不阻塞当前请求
        asyncio.create_task(_summarize_and_store(state, turn_count))

    return state


async def _summarize_and_store(state: PipelineState, turn_count: int):
    """
    把最近 SUMMARY_INTERVAL 轮对话压缩成摘要，存入 cold_memories 表。
    摘要包含: 核心话题、情绪变化、关键决策。
    """
    # 1. 获取最近 N 轮对话
    recent = await get_recent_turns(state["session_id"], SUMMARY_INTERVAL)
    dialogue = "\n".join(f"{t['role']}: {t['content']}" for t in recent)

    # 2. 用 LLM 压缩成摘要（小模型即可，花很少 token）
    summary = await llm_harness.generate(
        model=os.getenv("MODEL_CHEAP", "deepseek-chat"),
        messages=[{
            "role": "user",
            "content": f"请将以下对话压缩为 150 字以内的摘要，包含核心话题和情绪变化:\n\n{dialogue}"
        }],
        tenant_id=state["tenant_id"],
        max_tokens=200,
    )

    # 3. 生成 embedding 并存入 cold_memories
    embedding = generate_embedding(summary.content)
    store_cold_memory(
        tenant_id=state["tenant_id"],
        session_id=state["session_id"],
        summary=summary.content,
        emotion_tags=extract_emotion_tags(recent),
        embedding=embedding,
    )
```

## Subtask 04.08: 图组装 + 条件边

**文件:** `backend/pipeline/graph.py`
```python
from langgraph.graph import StateGraph, END

builder = StateGraph(PipelineState)
builder.add_node("auth_check", auth_check)
builder.add_node("load_memory", load_memory)
# ... 所有节点

# 条件边: 缓存命中 → END
builder.add_conditional_edges("cache_check", should_skip_to_end, {...})
# 条件边: model_router 短路径 → END
builder.add_conditional_edges("model_router", route_short_or_long, {...})

compiled_graph = builder.compile()
```

## Subtask 04.09: FastAPI 转接层（注入 user_context）

**文件:** `backend/pipeline/router.py`
```python
@router.post("/chat")
@observe(name="chat.pipeline")
async def chat_pipeline(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    initial = PipelineState(
        tenant_id=tenant.tenant_id,
        user_id=tenant.user_id,
        user_context={
            "tenant_id": tenant.tenant_id,
            "user_id": tenant.user_id,
            "permissions": tenant.extra_permissions,
            "role": tenant.role,
        },
        ...
    )
    final = await compiled_graph.ainvoke(initial)
    log_audit(background_tasks, ...)
    return ChatResponse(response=final["response"], ...)
```

## Subtask 04.10: 老代码退役

- `backend/services/chat_service.py` 加文件头 `# DEPRECATED: 请使用 pipeline/router.py`
- 新 `POST /chat` 路由走 pipeline，旧路由不动但不可达

## Subtask 04.11: SSE Streaming 入口（从 Task 02 延期）

> **依赖:** 04.09 转接层已就绪；真正逐 token 吐依赖 **07.07e** `LLMHarness.stream()`。
> 流式内容过滤（abort / retraction）依赖 **09.04**，本 subtask 只落路由骨架。

**文件:** `backend/pipeline/router.py` — 增加 `POST /chat/streaming`

**设计思路:**
- 短路径（缓存/Skill）→ 直接返回 JSON，不 SSE
- 长路径（LLM）→ SSE 逐 token 吐

```python
@router.post("/chat/streaming")
async def chat_streaming(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    tenant: TenantContext = Depends(require_permission("chat:write")),
):
    # 1. 跑完 model_router 之前的所有节点（快，<50ms）
    initial = make_initial_state(...)
    pre_state = await compiled_graph.ainvoke_until(initial, "model_router")

    # 2. 短路径 → 直接返回，不 SSE
    if pre_state["finish_reason"] in ("skill_executed", "cache_hit", "blocked"):
        return JSONResponse({"response": pre_state["response"]})

    # 3. 长路径 → SSE（stream 实现见 07.07e；abort/retraction 见 09.04）
    async def event_stream():
        async for token in llm_harness.stream(
            model=pre_state["selected_model"],
            messages=[{"role": "user", "content": pre_state["message"]}],
            tenant_id=tenant.tenant_id,
        ):
            yield f"data: {json.dumps({'token': token})}\n\n"
        background_tasks.add_task(run_post_llm_nodes, pre_state)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**验证:**
```bash
curl -N -X POST http://localhost:8000/chat/streaming \
  -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"message":"说说你的看法"}'
# → 逐字输出，不是一次性返回（需 07.07e 就绪）
```

## 验证

```bash
uv run python -c "
from backend.pipeline.graph import compiled_graph
print(f'✅ {len(compiled_graph.nodes)} 个节点编译成功')
"
```
