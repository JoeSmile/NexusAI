# NexusAI

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![CI](https://github.com/JoeSmile/NexusAI/actions/workflows/ci.yml/badge.svg)](https://github.com/JoeSmile/NexusAI/actions/workflows/ci.yml)

**The Governance Hub for Enterprise AI** — 企业 AI 中台的治理入口。

企业已有业务中台与数据中台，缺的是 **AI 治理层**。NexusAI 提供统一接入、能力编排、数据连接与合规兜底：应用可以跑在 Dify/自研上，**数据与调用必须过治理网关**。

[简体中文](README.md) · [English](README.en.md)

---

## Why NexusAI

| 我们做 | 我们不做 |
|--------|----------|
| 认证 / 多租户 RBAC / 审计 / 护栏 / 预算与密钥治理 | 再造一个通用 Agent 拖拽编排器 |
| Chat 管线 + Capability Hub + RAG，私有化可部署 | 替代业务中台 / 数据中台 |
| 模型可换（OpenAI 兼容 + mock/record/replay） | 绑定单一云厂商模型 |

完整定位与五层推导见 [`docs/strategy/AI_MIDDLE_PLATFORM.md`](docs/strategy/AI_MIDDLE_PLATFORM.md)。

## Features

| Area | Status | Notes |
|------|--------|--------|
| Chat governance pipeline (LangGraph) | ✅ | Auth → memory → rate limit → cache → guardrails → intent → dual path (skill / LLM) |
| Dual path routing | ✅ | High-confidence intent → skill ($0); else → `LLMHarness` |
| Capability Hub | ✅ | Registry + invoke (model / tool / rag / agent); per-capability permission |
| RAG (pgvector) | ✅ | Upload, ask, retrieve; L1/L2 cache with normalize |
| RBAC (4 roles) | ✅ | `super_admin` · `auditor` · `tenant_admin` · `user` |
| Audit trail | ✅ | `audit_logs` + export for auditors |
| Guardrails | ✅ | Injection block · PII redact · output checks · circuit breaker |
| Observability | ✅ | LangFuse traces · Prometheus `/metrics` |
| LLM key governance | ✅ | Encrypted keys · failover chain · harness providers |
| Password login (test FE) | ✅ | Issues `cg_` API keys (Task 38) |
| Workbench buttons / OA connectors | ⏳ | Planned — IT-orchestrated chains first |
| Self-serve workflow canvas | ⏸ | V2 — not in current scope |

## Architecture

```text
Access          Chat · API (X-API-Key / HMAC) · Capability invoke · (workbench planned)
Orchestration   Capability registry / chains · LangGraph chat DAG · short/long path
Data            RAG / pgvector · (OA & finance connectors planned)
Governance      RBAC · audit · guardrails · rate limit · budget hooks
Cross-cutting   LangFuse · Prometheus · model registry · LLMHarness · Redis cache
```

Chat pipeline (simplified):

```text
auth_check → load_memory → rate_limiter → cache_check
  ├─ hit  → END
  └─ miss → guardrails_input → analyze → build_context
            → model_router
                 ├─ short: skill → END
                 └─ long:  llm_generate → guardrails_out → write_memory → END
```

Interview-oriented walkthroughs: [`learning/`](learning/README.md).

## Requirements

- Python **3.11+** and [uv](https://github.com/astral-sh/uv)
- Docker (PostgreSQL + pgvector; optional LangFuse / Redis via compose)
- Node.js 18+ (optional — test frontend)

## Quick Start

```bash
# 1. Infrastructure
docker compose -f docker-compose.local.yml up -d

# 2. Dependencies
uv sync

# 3. Seed API keys + vector fixtures (prints fresh cg_ keys once)
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_pgvector.py

# 4. API
uv run uvicorn backend.app:app --reload --port 8000

# 5. Smoke
curl -s http://localhost:8000/health
curl -s -X POST http://localhost:8000/chat \
  -H "X-API-Key: <paste-key-from-seed>" \
  -H "Content-Type: application/json" \
  -d '{"message":"你好","session_id":"demo","user_id":"alice"}'
```

OpenAPI: [http://localhost:8000/docs](http://localhost:8000/docs) · Metrics: [http://localhost:8000/metrics](http://localhost:8000/metrics)

### Test frontend (recommended for QA)

```bash
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_capabilities.py   # optional capability demos
uv run uvicorn backend.app:app --reload --port 8000

cd frontend && npm install && npm run dev    # http://localhost:5173
```

Login supports **password register/login** and **API Key** slots (four roles). Journeys: [`examples/qa/journeys/`](examples/qa/journeys/). Frontend notes: [`frontend/README.md`](frontend/README.md).

Copy `config.env.example` → `config.env` for LangFuse / LLM provider settings.

## Project layout

```text
backend/          FastAPI app, pipeline, core auth/harness, modules (rag/intent/llm)
frontend/         Vite test console (panels for chat, RAG, admin, audit, …)
scripts/          seed, audit consistency, service helpers
examples/qa/      Manual QA scripts & journeys
learning/         Interview-oriented module deep-dives
docs/             Architecture, deployment, strategy, manual test
tasks/            Active design notes (e.g. Task 39 preprocess)
```

## Documentation

| Doc | Description |
|-----|-------------|
| [AI middle platform](docs/strategy/AI_MIDDLE_PLATFORM.md) | Positioning & five-layer map |
| [Strategy index](docs/strategy/README.md) | Moat / job-hunt / market notes |
| [Architecture](docs/ARCHITECTURE.md) | Technical architecture |
| [Cache](docs/CACHE.md) | Cache key semantics |
| [Deployment](docs/DEPLOYMENT.md) | Deploy notes |
| [Manual test](docs/MANUAL_TEST.md) | Acceptance & panel checks |
| [Roadmap](docs/ROADMAP.md) | Roadmap |
| [LangFuse QA](examples/qa/LANGFUSE.md) | How to read traces |
| [Competitive notes](docs/COMPETITIVE_ANALYSIS.md) | Landscape sketch |
| [Windows setup](docs/WINDOWS_SETUP.md) | Windows tips |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version:

1. Fork → branch (`feat/` / `fix/` / `docs/`)
2. `uv run ruff check backend/ scripts/` · `uv run pytest` · frontend tests if touched
3. Conventional Commits + `Signed-off-by:`

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Acknowledgments

Built for private / on-prem enterprise AI governance scenarios (multi-tenant, auditability, data residency). Stack highlights: FastAPI, LangGraph, PostgreSQL/pgvector, LangFuse, Prometheus.
