# NexusAI

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-green)]()
[![CI](https://github.com/joe/context-gate/actions/workflows/ci.yml/badge.svg)]()

> **The Governance Hub for Enterprise AI**

Every enterprise has a business middle platform and a data middle platform — what's missing is an AI middle platform. NexusAI fills that gap: **a unified entry point to enterprise AI capabilities, with capabilities orchestrated by IT, data connected from internal OA/RAG, and a governance layer as the safety net.**

[简体中文](README.md) | [English](README.en.md)

## Positioning

- **Governance is the selling point, not a feature.** Audit, budget, permissions, compliance — answering the enterprise's one question: "would you dare hand your data to it?"
- **Not an agent orchestration platform.** Dify/Coze build application orchestration; NexusAI does governance — apps can run on Dify, but data must pass through NexusAI.
- **Not another middle platform.** Enterprises already have business/data middle platforms; NexusAI adds an AI governance layer on top of them.

The full derivation of the positioning and five-layer architecture is in [`docs/strategy/AI_MIDDLE_PLATFORM.md`](docs/strategy/AI_MIDDLE_PLATFORM.md) (decision made 2026-08-05).

## Architecture (Five Layers)

```
Access Layer       chat (intent detection) / workbench buttons (direct invoke) / API (X-API-Key + HMAC)
Orchestration Layer  capability registry → capability chains (IT-orchestrated) → LangGraph DAG → dual path (skill direct $0 / LLM)
Data Connection Layer OA / RAG knowledge base / finance systems (tenant + role + row-level isolation, data stays in-domain)
Governance Layer    RBAC 4 roles / full audit / budget quotas / safety guardrails / approval flows
Cross-cutting Layer LangFuse observability / model routing + harness / cache / AES-256-GCM key governance
```

The technical core is a LangGraph directed acyclic graph (pipeline nodes):

```
auth_check → load_memory → rate_limiter → cache_check
  ├─ hit → END
  └─ miss → guardrails_input → analyze_parallel → build_context
            → model_router
              ├─ short path → execute skill → END (50ms, $0)
              └─ long path → llm_generate → guardrails_output
                            → write_memory + audit → END (1-5s)
```

## Quick Start

```bash
# 1. Start infrastructure (PostgreSQL + pgvector)
docker compose -f docker-compose.local.yml up -d

# 2. Install dependencies
uv sync

# 3. Initialize data
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_pgvector.py

# 4. Start the API
uv run uvicorn backend.app:app --reload

# 5. Test
curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "session_id": "test", "user_id": "alice"}'
```

### Test Frontend (Task 30, recommended QA entry)

```bash
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_capabilities.py   # capability chain demo (optional)
uv run uvicorn backend.app:app --reload --port 8000
cd frontend && npm install && npm run dev    # http://localhost:5173
```

The login page supports **password register/login** (Task 38) and Key login (4 role slots, for QA role switching).
Switch roles from the top-right corner → walk the panels against [`examples/qa/journeys/`](examples/qa/journeys/).
Detailed steps and panel docs: [`frontend/README.md`](frontend/README.md).

## Feature Matrix

| Capability | Status | Notes |
|------|------|------|
| Unified entry: chat / button / API | 🚧 Partial | chat→capability-chain bridge in progress (chat currently goes intent→skill, capability chains use invoke; the two paths are not yet connected) |
| Capability orchestration: registry + chains | ✅ | Capability catalog + permission binding; chained orchestration (rag-ask → contract-query → vendor-risk) |
| Dual-path execution | ✅ | Intent confidence ≥0.85 → direct skill (50ms, $0), otherwise LLM pipeline |
| RAG knowledge base | ✅ | pgvector + upload / Q&A / retrieval / semantic recall |
| RBAC 4 roles | ✅ | super_admin / tenant_admin / auditor / user |
| Full audit | ✅ | audit_logs + compliance export (redacted) |
| Budget quotas | ✅ | Task 32: per-call / daily / monthly three-window limits + approval dual ledgers |
| Safety guardrails | ✅ | injection detection + PII redaction + output review + circuit breaker |
| Data connectors (OA / finance) | ⏳ Planned | phase 1: import + scheduled sync |
| Workbench button page | ⏳ Planned | button → direct invoke, one-click execution for business users |

## Comparison

|   | NexusAI | Dify | FastGPT |
|---|------------|------|---------|
| Positioning | Enterprise AI middle platform (governance + data) | AI app orchestration platform | Knowledge base Q&A |
| Tenant isolation | ✅ row-level + audit | ✅ | ❌ |
| Audit | ✅ full + export | ❌ | ❌ |
| Signed auth | ✅ HMAC-SHA256 | ❌ | ❌ |
| API key governance | ✅ AES-256-GCM | ❌ | ❌ |
| Safety guardrails | ✅ injection+PII+output | ⚠️ basic | ❌ |
| Observability | ✅ LangFuse | ✅ | ⚠️ |
| Enterprise data (OA/RAG) connectivity | ✅ RAG built-in, OA planned | ⚠️ | ❌ |

## Phases

- **First battle (now):** no self-service workflow orchestration. IT configures capability chains; business users invoke via chat or workbench buttons.
- **V2 goal:** self-service orchestration (templates + form-first, drag-and-drop canvas later), approval nodes (reconciliation/procurement flows need leader sign-off), blueprint scenarios (accounting reconciliation).

## Docs

- [Strategy](docs/strategy/README.md) — moat / survival rate / job-hunting playbook
- [AI Middle Platform Positioning](docs/strategy/AI_MIDDLE_PLATFORM.md) — one-line positioning + five-layer architecture (decided 2026-08-05)
- [Architecture](docs/ARCHITECTURE.md)
- [Compliance](docs/COMPLIANCE.md)
- [Security Policy](docs/SECURITY.md)
- [Security Audit](docs/SECURITY_AUDIT.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Roadmap](docs/ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Code of Conduct](docs/CODE_OF_CONDUCT.md)

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE)
