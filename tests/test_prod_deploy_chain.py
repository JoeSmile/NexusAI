"""Task 74 — prod nginx/compose contracts (no Docker required)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGINX = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
NGINX_LF = (ROOT / "deploy" / "nginx.langfuse.conf").read_text(encoding="utf-8")
COMPOSE_PROD = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")


def test_default_nginx_keeps_api_prefix() -> None:
    assert "proxy_pass http://nexusai_upstream/;" not in NGINX
    assert "location /api/" in NGINX
    assert "proxy_pass http://nexusai_upstream;" in NGINX


def test_default_nginx_has_no_langfuse_upstream() -> None:
    assert "langfuse_upstream" not in NGINX
    assert "langfuse-web" not in NGINX


def test_langfuse_nginx_declares_upstream() -> None:
    assert "upstream langfuse_upstream" in NGINX_LF
    assert "server langfuse-web:3000;" in NGINX_LF
    assert "location /langfuse/" in NGINX_LF


def test_spa_location_is_after_api_and_chat() -> None:
    api_at = NGINX.index("location /api/")
    chat_at = NGINX.index("location /chat")
    spa_at = NGINX.index("try_files $uri $uri/ /index.html;")
    assert api_at < spa_at
    assert chat_at < spa_at


def test_chat_sse_http11_and_empty_connection() -> None:
    chat_block = NGINX.split("location /chat", 1)[1].split("location ", 1)[0]
    assert "proxy_http_version 1.1;" in chat_block
    assert 'proxy_set_header Connection "";' in chat_block
    assert "proxy_buffering off;" in chat_block
    assert "proxy_read_timeout 300s;" in chat_block


def test_health_is_not_under_api_prefix() -> None:
    assert "location /health" in NGINX
    assert "location /api/health" not in NGINX


def test_health_forwards_x_forwarded_headers() -> None:
    health_block = NGINX.split("location /health", 1)[1].split("location ", 1)[0]
    assert "X-Forwarded-For" in health_block
    assert "X-Forwarded-Proto" in health_block


def test_prod_compose_sqlite_fallback_off() -> None:
    assert 'USE_SQLITE_FALLBACK: "0"' in COMPOSE_PROD


def test_prod_compose_has_one_shot_migrate() -> None:
    assert "alembic" in COMPOSE_PROD
    assert "service_completed_successfully" in COMPOSE_PROD
    assert 'restart: "no"' in COMPOSE_PROD


def test_prod_compose_has_no_langfuse_required_vars() -> None:
    assert "\n  langfuse-web:" not in COMPOSE_PROD
    assert "LANGFUSE_DB_PASSWORD:?" not in COMPOSE_PROD


def test_langfuse_overlay_exists_and_requires_public_urls() -> None:
    overlay = (ROOT / "docker-compose.langfuse.yml").read_text(encoding="utf-8")
    assert "langfuse-web" in overlay
    assert "NEXTAUTH_URL:?" in overlay or "NEXTAUTH_URL: ${NEXTAUTH_URL:?" in overlay
    assert "3001:3000" not in overlay
    assert "9090:9000" not in overlay


def test_prod_compose_intent_model_volume() -> None:
    assert "data/models/intent_v8" in COMPOSE_PROD


def test_prod_compose_nginx_uses_boot_script() -> None:
    assert "nginx-boot.sh" in COMPOSE_PROD
    assert "frontend/dist" in COMPOSE_PROD
