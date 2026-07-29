# ContextGate

> The Intelligent Gateway for LLM Context Management

Enterprise LLM pre-processing pipeline with auth, multi-tenancy, guardrails, observability, model routing, and caching.

[简体中文](README.md) | [English](README.en.md)

## Quick Start

```bash
# 1. Start infrastructure
docker compose -f docker-compose.local.yml up -d

# 2. Install dependencies
uv sync

# 3. Initialize database
uv run python -c "from backend.database.pgvector_session import PGVectorSession; PGVectorSession().init_db()"

# 4. Seed API keys
uv run python scripts/seed_api_keys.py

# 5. Start the API
uv run uvicorn backend.app:app --reload
```

Dev test client (frontend): http://localhost:3000 (to be replaced by Playground in v1.0)

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## License

Apache 2.0
