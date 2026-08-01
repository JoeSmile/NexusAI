.PHONY: help sync lock install up up-langfuse up-all down db-init run lint typecheck test check verify seed fmt docker-up docker-down clean

ROOT_DIR := $(patsubst %/,%,$(dir $(abspath $(firstword $(MAKEFILE_LIST)))))
UV := $(shell command -v uv 2> /dev/null)
COMPOSE_LOCAL := docker compose -f docker-compose.local.yml

define require_uv
	@if [ -z "$(UV)" ]; then \
		echo "❌ uv 未安装: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		exit 1; \
	fi
endef

help:
	@echo "ContextGate — 常用命令"
	@echo ""
	@echo "  make sync / install  安装依赖 (uv sync)"
	@echo "  make lock            更新 uv.lock"
	@echo "  make up              只起 postgres"
	@echo "  make up-langfuse     起 postgres + LangFuse UI (:3001)"
	@echo "  make up-all          起全部 compose 服务"
	@echo "  make down            停止本地基础设施"
	@echo "  make db-init         初始化 pgvector 表"
	@echo "  make run             启动 API (uvicorn --reload)"
	@echo "  make seed            写入开发用 API Key + 示例数据"
	@echo "  make lint            ruff check"
	@echo "  make typecheck       mypy backend/"
	@echo "  make test            pytest"
	@echo "  make fmt             ruff format"
	@echo "  make clean           清理 __pycache__"
	@echo ""
	@echo "典型流程: make up && make sync && make db-init && make seed && make run"

sync install:
	$(require_uv)
	cd $(ROOT_DIR) && uv sync --extra dev

lock:
	$(require_uv)
	cd $(ROOT_DIR) && uv lock

up:
	cd $(ROOT_DIR) && $(COMPOSE_LOCAL) up -d postgres

up-langfuse:
	cd $(ROOT_DIR) && $(COMPOSE_LOCAL) up -d postgres langfuse-db-init langfuse

up-all docker-up:
	cd $(ROOT_DIR) && $(COMPOSE_LOCAL) up -d --build

down docker-down:
	cd $(ROOT_DIR) && $(COMPOSE_LOCAL) down

db-init:
	$(require_uv)
	cd $(ROOT_DIR) && \
		DATABASE_URL=$${DATABASE_URL:-postgresql://contextgate:contextgate_local@localhost:5432/contextgate} \
		uv run --no-sync alembic upgrade head

run:
	$(require_uv)
	cd $(ROOT_DIR) && \
		APP_ENV=$${APP_ENV:-dev} \
		DATABASE_URL=$${DATABASE_URL:-postgresql://contextgate:contextgate_local@localhost:5432/contextgate} \
		uv run --no-sync uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000

demo:
	$(require_uv)
	cd $(ROOT_DIR) && \
		APP_ENV=demo \
		uv run --no-sync uvicorn backend.app:app --host 0.0.0.0 --port 8000

seed:
	$(require_uv)
	cd $(ROOT_DIR) && \
		APP_ENV=$${APP_ENV:-dev} \
		DATABASE_URL=$${DATABASE_URL:-postgresql://contextgate:contextgate_local@localhost:5432/contextgate} \
		uv run --no-sync python scripts/seed_api_keys.py
	cd $(ROOT_DIR) && \
		APP_ENV=$${APP_ENV:-dev} \
		DATABASE_URL=$${DATABASE_URL:-postgresql://contextgate:contextgate_local@localhost:5432/contextgate} \
		uv run --no-sync python scripts/seed_pgvector.py

lint:
	$(require_uv)
	cd $(ROOT_DIR) && uv run --no-sync ruff check backend/ scripts/

typecheck:
	$(require_uv)
	cd $(ROOT_DIR) && uv run --no-sync mypy --ignore-missing-imports

fmt:
	$(require_uv)
	cd $(ROOT_DIR) && uv run --no-sync ruff format backend/ scripts/

test:
	$(require_uv)
	cd $(ROOT_DIR) && \
		APP_ENV=test \
		LLM_PROVIDER=replay \
		DATABASE_URL=$${DATABASE_URL:-postgresql://contextgate:contextgate_local@localhost:5432/contextgate} \
		uv run --no-sync pytest tests/ -v

check: lint typecheck

clean:
	find $(ROOT_DIR) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find $(ROOT_DIR) -type f -name "*.pyc" -delete

verify:
	$(require_uv)
	@echo "== brand =="
	@cd $(ROOT_DIR) && grep -rE "心语|情感陪伴|xinyu|emotional_chat|emotional-chat|温暖耐心|我理解你的感受|倾听你的感受|Psychology|EMOTIONAL_CHAT" --include="*.py" --include="*.sh" --include="*.html" --include="*.js" --include="*.ps1" . 2>/dev/null | grep -v "^\./\.venv/\|^\./\.git/\|^\./tasks/\|^\./scripts/audit_consistency.py" && echo "❌ brand" && exit 1 || echo "✅ 无情感化字眼"
	@echo "== project name =="
	@grep "name.*=.*emotional-chat" $(ROOT_DIR)/pyproject.toml && echo "❌ name" && exit 1 || echo "✅ 项目名已改"
	@echo "== imports =="
	cd $(ROOT_DIR) && uv run --no-sync python -c "\
from backend.database.pgvector_session import PGVectorSession, get_pg_session; \
from pgvector.sqlalchemy import Vector; \
from backend.database.vector_ops import store_embedding, search_memories, delete_expired_entries; \
from backend.database import _resolve_database_url; \
print('✅ pgvector / vector_ops'); \
print('✅ database URL:', _resolve_database_url())"
