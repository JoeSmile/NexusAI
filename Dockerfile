# NexusAI — Multi-stage Docker build with uv
FROM python:3.11-slim AS builder

# uv 二进制：docker hub 无官方 astral-sh/uv 镜像（仅 ghcr.io，大陆直连不可达）；
# 用 pip 从清华 PyPI 安装，同时把 uv 的默认索引指向清华避免 pypi.org 慢
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple uv
ENV UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra intent-model

COPY . .
RUN uv sync --frozen --no-dev --extra intent-model

FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /app/uploads /app/data /app/logs && \
    chown -R appuser:appuser /app/uploads /app/data /app/logs

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["python", "-m", "apps.api.run_api"]
