# ContextGate

> The Intelligent Gateway for LLM Context Management

企业级 LLM 前置处理管线，支持认证、多租户、安全护栏、可观测、模型路由、缓存。

[简体中文](README.md) | [English](README.en.md)

## Quick Start

```bash
# 1. 启动基础设施（postgres + pgvector）
make up

# 2. 安装依赖
make sync

# 3. 初始化数据库
make db-init

# 4. 启动服务
make run
```

开发期测试客户端（前端）: http://localhost:3000（v1.0 将替换为 Playground）

API Key 种子脚本见 Batch 6：`scripts/seed_api_keys.py`（尚未合入时可用手工插入 `api_keys` 表）。

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## License

Apache 2.0
