.PHONY: help sync lock up up-all down db-init run lint typecheck test check verify

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
	@echo "  make sync       安装/同步依赖 (uv sync)"
	@echo "  make lock       更新 uv.lock"
	@echo "  make up         只起 postgres（推荐本地开发，不构建镜像）"
	@echo "  make up-all     起全部 compose 服务（会 build contextgate，需能拉 Docker Hub）"
	@echo "  make down       停止本地基础设施"
	@echo "  make db-init    初始化 pgvector 表"
	@echo "  make run        启动 API (uvicorn --reload)"
	@echo "  make lint       ruff check"
	@echo "  make typecheck  mypy backend/"
	@echo "  make test       pytest"
	@echo "  make check      lint + typecheck"
	@echo "  make verify     Batch 1 验收检查"
	@echo ""
	@echo "典型流程: make up && make sync && make db-init && make run"

sync:
	$(require_uv)
	cd $(ROOT_DIR) && uv sync --extra dev

lock:
	$(require_uv)
	cd $(ROOT_DIR) && uv lock

# 本地开发：只起 DB，API 用 make run（避免 build python 镜像拉不到 Docker Hub）
up:
	cd $(ROOT_DIR) && $(COMPOSE_LOCAL) up -d postgres

up-all:
	cd $(ROOT_DIR) && $(COMPOSE_LOCAL) up -d --build

down:
	cd $(ROOT_DIR) && $(COMPOSE_LOCAL) down

db-init:
	$(require_uv)
	cd $(ROOT_DIR) && \
		DATABASE_URL=$${DATABASE_URL:-postgresql://contextgate:contextgate_local@localhost:5432/contextgate} \
		uv run --no-sync python -c "from backend.database.pgvector_session import PGVectorSession; PGVectorSession().init_db(); print('✅ db initialized')"

run:
	$(require_uv)
	cd $(ROOT_DIR) && \
		DATABASE_URL=$${DATABASE_URL:-postgresql://contextgate:contextgate_local@localhost:5432/contextgate} \
		uv run --no-sync uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000

lint:
	$(require_uv)
	cd $(ROOT_DIR) && uv run --no-sync ruff check .

typecheck:
	$(require_uv)
	cd $(ROOT_DIR) && uv run --no-sync mypy backend/

test:
	$(require_uv)
	cd $(ROOT_DIR) && uv run --no-sync pytest

check: lint typecheck

verify:
	$(require_uv)
	@echo "== brand =="
	@grep -r "心语\|情感陪伴" $(ROOT_DIR)/backend/ --include="*.py" && echo "❌ brand" && exit 1 || echo "✅ 无情感化字眼"
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
