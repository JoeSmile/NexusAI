# NexusAI

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![CI](https://github.com/JoeSmile/NexusAI/actions/workflows/ci.yml/badge.svg)](https://github.com/JoeSmile/NexusAI/actions/workflows/ci.yml)

**The Governance Hub for Enterprise AI.**

Enterprises already have business and data platforms. What’s missing is an **AI governance layer**. NexusAI is a unified gateway for access, capability orchestration, internal data (RAG and planned OA), and compliance — apps may run on Dify or custom stacks; **calls and data should pass through governance**.

[简体中文](README.md) · [English](README.en.md)

---

## Why NexusAI

| We build | We don’t |
|----------|----------|
| Auth, multi-tenant RBAC, audit, guardrails, key & cost controls | Another general-purpose agent drag-and-drop studio |
| Chat pipeline + Capability Hub + RAG, privatizable | A replacement for existing business/data platforms |
| Swappable models (OpenAI-compatible + mock/record/replay) | Lock-in to a single cloud LLM |

Full positioning: [`docs/strategy/AI_MIDDLE_PLATFORM.md`](docs/strategy/AI_MIDDLE_PLATFORM.md).

## Features

| Area | Status | Notes |
|------|--------|--------|
| Chat governance pipeline (LangGraph) | ✅ | Auth → memory → rate limit → cache → guardrails → intent → dual path |
| Dual path routing | ✅ | High-confidence intent → skill ($0); else → `LLMHarness` |
| Capability Hub | ✅ | Registry + invoke; per-capability permission |
| RAG (pgvector) | ✅ | Upload / ask / retrieve; L1/L2 cache |
| RBAC (4 roles) | ✅ | `super_admin` · `auditor` · `tenant_admin` · `user` |
| Audit trail | ✅ | `audit_logs` + export |
| Guardrails | ✅ | Injection · PII · output checks · circuit breaker |
| Observability | ✅ | LangFuse · Prometheus `/metrics` |
| LLM key governance | ✅ | Encrypted keys · failover · harness providers |
| Password login (test FE) | ✅ | Issues `cg_` API keys |
| Workbench / OA connectors | ⏳ | Planned |
| Self-serve workflow canvas | ⏸ | V2 — out of current scope |

## Architecture

```text
Access          Chat · API (X-API-Key / HMAC) · Capability invoke · (workbench planned)
Orchestration   Capability registry / chains · LangGraph chat DAG · short/long path
Data            RAG / pgvector · (OA & finance planned)
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

Deep-dives for interviews: [`learning/`](learning/README.md).

## Requirements

- Python **3.11+** and [uv](https://github.com/astral-sh/uv)
- Docker (PostgreSQL + pgvector; optional LangFuse / Redis)
- Node.js 18+ (optional test frontend)

## Quick Start

```bash
# 1. Infrastructure
docker compose -f docker-compose.local.yml up -d

# 2. Dependencies
uv sync

# 3. Seed (prints fresh cg_ keys once to stdout)
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_pgvector.py

# 4. API
uv run uvicorn backend.app:app --reload --port 8000

# 5. Smoke
curl -s http://localhost:8000/health
curl -s -X POST http://localhost:8000/chat \
  -H "X-API-Key: <paste-key-from-seed>" \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","session_id":"demo","user_id":"alice"}'
```

OpenAPI: `http://localhost:8000/docs` · Metrics: `http://localhost:8000/metrics`

### Test frontend

```bash
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_capabilities.py
uv run uvicorn backend.app:app --reload --port 8000
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Password login and API-key role slots are supported. See [`frontend/README.md`](frontend/README.md) and [`examples/qa/journeys/`](examples/qa/journeys/).

Copy `config.env.example` → `config.env` for LangFuse / LLM settings.

## Project layout

```text
backend/       FastAPI, pipeline, auth/harness, modules (rag/intent/llm)
frontend/      Vite test console
scripts/       Seed & helpers
examples/qa/   Manual QA
learning/      Module deep-dives
docs/          Architecture, deploy, strategy, manual tests
tasks/         Active design notes
```

## Documentation

| Doc | Description |
|-----|-------------|
| [AI middle platform](docs/strategy/AI_MIDDLE_PLATFORM.md) | Positioning |
| [Strategy index](docs/strategy/README.md) | Moat / GTM notes |
| [Architecture](docs/ARCHITECTURE.md) | Tech architecture |
| [Cache](docs/CACHE.md) | Cache semantics |
| [Deployment](docs/DEPLOYMENT.md) | Deploy |
| [Manual test](docs/MANUAL_TEST.md) | Acceptance |
| [Roadmap](docs/ROADMAP.md) | Roadmap |
| [LangFuse QA](examples/qa/LANGFUSE.md) | Reading traces |
| [Competitive notes](docs/COMPETITIVE_ANALYSIS.md) | Landscape |
| [Windows setup](docs/WINDOWS_SETUP.md) | Windows |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md): branch → lint/tests → Conventional Commits with `Signed-off-by:`.

## License

Apache License 2.0 — [LICENSE](LICENSE) · [NOTICE](NOTICE).

## Acknowledgments

Aimed at private / on-prem enterprise AI governance (tenancy, audit, residency). Stack: FastAPI, LangGraph, PostgreSQL/pgvector, LangFuse, Prometheus.
