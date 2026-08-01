# Task 08: 依赖锁定

**Subtask:** 运行 `uv lock && uv sync`

```bash
uv lock && uv sync
```

## 验证

```bash
uv run python -c "import langgraph, langfuse; print('✅ all deps ok')"
```
