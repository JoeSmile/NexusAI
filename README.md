# ContextGate

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-green)]()
[![CI](https://github.com/joe/context-gate/actions/workflows/ci.yml/badge.svg)]()

> **The Intelligent Gateway for LLM Context Management**

企业级 LLM 前置处理管线 — 认证、多租户、安全护栏、可观测、模型路由、缓存、加密 Key 管理。

[简体中文](README.md) | [English](README.en.md)

## Architecture

```
用户 → FastAPI → LangGraph StateGraph → pgvector → LangFuse
                ↑
      Auth(RBAC0) → Guardrails → Prometheus
```

管线节点：

```
auth_check → load_memory → rate_limiter → cache_check
  ├─ hit → END
  └─ miss → guardrails_input → analyze_parallel → build_context
            → model_router
              ├─ short path → execute skill → END (50ms)
              └─ long path → llm_generate → guardrails_output
                            → write_memory + audit → END (1-5s)
```

## 前置要求

- **Docker** — PostgreSQL + pgvector 基础设施（`make up`）
- **uv** — Python 包管理（自动管理 Python 3.11+，无需单独装 Python）
- **git**

macOS / Windows / Linux 均可，命令完全一致。

## Quick Start

```bash
# 1. 启动基础设施
docker compose -f docker-compose.local.yml up -d

# 2. 安装依赖
uv sync

# 3. 初始化数据
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_pgvector.py

# 4. 启动服务
uv run uvicorn backend.app:app --reload

# 5. 测试
curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: cg_***" \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "session_id": "test", "user_id": "alice"}'
```

开发期轻量测试页: http://localhost:8000/playground/（`examples/` 静态挂载）  
- Admin: `/playground/admin.html`  
- SSE: `/playground/streaming.html` → `POST /chat/streaming`（空闲约 15s `: ping`；断开即中止；**暂不支持 `Last-Event-ID` 断点续传**）

### 测试前端（Task 30，推荐 QA 主入口）

```bash
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_capabilities.py   # Agent 嵌套演示可选
uv run uvicorn backend.app:app --reload --port 8000
cd frontend && npm install && npm run dev    # http://localhost:5173
```

在登录页填入 4 角色 Key → 右上角切换角色 → 对照 [`examples/qa/journeys/`](examples/qa/journeys/) 走面板。  
详细步骤与面板说明见 [`frontend/README.md`](frontend/README.md)。  
`examples/*.html` 仍保留（playground 挂载不动）；新 QA 优先用测试 FE。

## Features

| Feature | Status | Description |
|---------|--------|-------------|
| Auth + RBAC0 | ✅ | API Key 认证 + 4 角色权限模型 |
| Request Signature | ✅ | HMAC-SHA256 防重放签名 |
| Multi-tenant | ✅ | 租户隔离 + 数据行级隔离 |
| Audit Logging | ✅ | 全量审计 + CSV 导出 |
| LangGraph Pipeline | ✅ | 10 节点 DAG 管线 |
| LangFuse Tracing | ✅ | 全链路可观测 |
| Cache (Exact + Fingerprint) | ✅ | 精确匹配 + 意图指纹缓存 |
| Cost Management | ✅ | 预算控制 + 模型路由 |
| Skill Dual-path | ✅ | 短路径(50ms) + 长路径(LLM) |
| Security Guardrails | ✅ | 注入检测 + PII 脱敏 + 输出审查 |
| File Upload Hardening | ✅ | MIME 头检测 + UUID 重命名 |
| Circuit Breaker | ✅ | LLM 故障自动降级 |
| Health Check | ✅ | 深度健康检查 + SLA 指标 |
| Error Codes | ✅ | 结构化错误码统一响应 |
| LLM API Key Governance | ✅ | AES-256-GCM 加密 + 租户隔离 |
| Docker + CI/CD | ✅ | Multi-stage build + GitHub Actions |
| Playground | ✅ | 4-Tab 测试页面 |

## Comparison

|   | ContextGate | Dify | FastGPT |
|---|------------|------|---------|
| 架构 | LangGraph DAG | Workflow Builder | Workflow |
| 租户隔离 | ✅ 行级 + 审计 | ✅ | ❌ |
| 审计 | ✅ 全量 + 导出 | ❌ | ❌ |
| 签名认证 | ✅ HMAC-SHA256 | ❌ | ❌ |
| API Key 治理 | ✅ AES-256-GCM | ❌ | ❌ |
| 安全护栏 | ✅ 注入+PII+输出 | ⚠️ 基础 | ❌ |
| 可观测 | ✅ LangFuse | ✅ | ⚠️ |
| 定位 | 企业 LLM 网关 | 应用平台 | 知识库 |

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Compliance](docs/COMPLIANCE.md)
- [Security Policy](docs/SECURITY.md)
- [Security Audit](docs/SECURITY_AUDIT.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Roadmap](docs/ROADMAP.md)
- [Strategy](docs/strategy/README.md) — 护城河 / 生存率 / 求职打法
- [Contributing](CONTRIBUTING.md)
- [Code of Conduct](docs/CODE_OF_CONDUCT.md)

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE)
