# ContextGate

> The Intelligent Gateway for LLM Context Management

Enterprise LLM pre-processing pipeline with auth, multi-tenancy, guardrails, observability, model routing, and caching.

[简体中文](README.md) | [English](README.en.md)

## Quick Start

```bash
# 1. Start infrastructure (postgres + pgvector)
make up

# 2. Install dependencies
make sync

# 3. Initialize database
make db-init

# 4. Start the API
make run
```

Dev test client (frontend): http://localhost:3000 (to be replaced by Playground in v1.0)

API key seeding lands in Batch 6 (`scripts/seed_api_keys.py`).

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## License

Apache 2.0
