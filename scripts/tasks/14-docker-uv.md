# Task 14: Docker + uv 最终化

## Subtask 14.01: Dockerfile 重写（uv multi-stage）

**文件:** `Dockerfile`
```dockerfile
FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.11-slim
RUN groupadd -r appuser && useradd -r -g appuser appuser
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY . .
USER appuser
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Subtask 14.02: docker-compose.local.yml 最终化

**修改:** `docker-compose.local.yml`
- service: `contextgate` — 从 builder 构建，本地代码挂载
- service: `postgres` — pgvector/pgvector:pg16
- service: `langfuse` — ghcr.io/langfuse/langfuse:latest
- networks + volumes

## Subtask 14.03: Makefile 更新

**修改:** `Makefile`
- `install` → `uv sync`
- `run` → `uv run uvicorn backend.app:app`
- 删除 pip 相关命令

## Subtask 14.04: config.env

**创建:** `config.env`
```env
DATABASE_URL=postgresql://emotional_chat:emotional_chat_local@localhost:5432/emotional_chat
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-local-dev
LANGFUSE_SECRET_KEY=sk-local-dev
LLM_API_KEY=your_key_here
LLM_BASE_URL=https://api.deepseek.com
DEFAULT_MODEL=deepseek-chat
LLM_MOCK=true
```

## 验证

```bash
docker compose -f docker-compose.local.yml up -d
docker compose ps  # → 全部 healthy
```
