# Task 05: LangFuse 可观测性

> `@observe` 在异步函数上用 `as_type="generation"` 记录 token/cost。
> **前置依赖:** `tasks/04-langgraph-pipeline.md`（需要 pipeline 节点）
> **完成后:** 无（独立 Task，与 06/07/09/10/11/12 可并行）

## Subtask 05.01: 客户端初始化

**文件:** `backend/observability/langfuse_client.py`
```python
from langfuse import Langfuse
_lf: Langfuse | None = None

def get_langfuse() -> Langfuse:
    global _lf
    if _lf is None:
        _lf = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "pk-local-dev"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY", "sk-local-dev"),
            host=os.getenv("LANGFUSE_HOST", "http://localhost:3000"),
        )
    return _lf
```

## Subtask 05.02: 管线节点埋点

每个节点函数加 `@observe()`：
```python
@observe(name="pipeline.llm_generate", as_type="generation")
async def llm_generate(state):
    response = await call_llm(...)
    langfuse_context.update_current_generation(
        model=state["selected_model"],
        input=state["message"],
        output=response,
        usage={"input": tokens_in, "output": tokens_out}
    )
    ...
```

## Subtask 05.03: FastAPI 路由集成

在 `pipeline/router.py` 的入口函数上加 `@observe()`。
Trace name: `chat_{tenant_id}/{session_id}`

## 验证

发消息 → `http://localhost:3001` 看到完整 trace
