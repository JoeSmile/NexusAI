# ContextGate

> The Intelligent Gateway for LLM Context Management

企业级 LLM 前置处理管线，支持认证、多租户、安全护栏、可观测、模型路由、缓存。

[简体中文](README.md) | [English](README.en.md)

## Quick Start

```bash
# 1. 启动基础设施
docker compose -f docker-compose.local.yml up -d

# 2. 安装依赖
uv sync

# 3. 初始化数据库
uv run python -c "from backend.database.pgvector_session import PGVectorSession; PGVectorSession().init_db()"

# 4. 创建 API Key
uv run python scripts/seed_api_keys.py

# 5. 启动服务
uv run uvicorn backend.app:app --reload
```

开发期测试客户端（前端）: http://localhost:3000（v1.0 将替换为 Playground）

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## License

Apache 2.0
