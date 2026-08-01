# Task 11: 断路器 + 降级

> LLM 挂了不抛 500，返回友好降级回复。

## Subtask 11.01: CircuitBreaker

**文件:** `backend/core/circuit_breaker.py`
```
closed → (5次失败) → open → (30秒) → half-open → (1次成功) → closed
```

## Subtask 11.02: Fallback 回复

**文件:** `backend/core/fallback.py`
```python
FALLBACK = {
    "zh": "系统暂时繁忙，请稍后再试。",
    "en": "Service temporarily unavailable.",
}
```

## Subtask 11.03: 嵌入 llm_generate

**修改:** `backend/pipeline/nodes/llm_generate.py`
```python
breaker = CircuitBreaker()

async def llm_generate(state: PipelineState) -> PipelineState:
    result = await breaker.call(
        fn=lambda: call_llm(state["message"]),
        fallback_fn=lambda: FALLBACK.get("zh", ""),
    )
    state["response"] = result
    return state
```

## 验证

关掉 API key → 返回降级回复，HTTP 200，不是 500
