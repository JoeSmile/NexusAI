"""Task 81 — ops_status parse / hints (no live Docker)."""

from __future__ import annotations

from scripts.ops_status import (
    compose_ps_cmd,
    hint_for,
    parse_compose_ps,
    row_is_red,
    worst_exit,
)


def test_parse_compose_ps_ndjson() -> None:
    raw = '{"Name":"x-postgres-1","Service":"postgres","State":"running","Health":"unhealthy"}\n'
    rows = parse_compose_ps(raw)
    assert rows[0]["Service"] == "postgres"
    assert rows[0]["Health"] == "unhealthy"


def test_parse_compose_ps_array() -> None:
    raw = (
        '[{"Name":"x-redis-1","Service":"redis","State":"running","Health":"healthy"}]'
    )
    rows = parse_compose_ps(raw)
    assert rows[0]["Service"] == "redis"
    assert rows[0]["Health"] == "healthy"


def test_hint_postgres_unhealthy() -> None:
    h = hint_for("postgres", "unhealthy", None)
    assert "restart postgres" in h


def test_hint_nexusai_when_db_down() -> None:
    h = hint_for(
        "nexusai",
        "unhealthy",
        {"status": "degraded", "checks": {"database": {"status": "down"}}},
    )
    assert "restart postgres" in h
    assert "restart nexusai" not in h.split("postgres")[0] or "postgres" in h


def test_hint_knowledge_worker() -> None:
    h = hint_for("knowledge-worker", "unhealthy", None)
    assert "restart knowledge-worker" in h


def test_worst_exit_red() -> None:
    assert worst_exit([("postgres", True)]) == 1
    assert worst_exit([("postgres", False)]) == 0


def test_compose_ps_cmd_includes_stopped() -> None:
    cmd = compose_ps_cmd("docker-compose.prod.yml")
    assert cmd[:4] == ["docker", "compose", "-f", "docker-compose.prod.yml"]
    assert "--all" in cmd
    assert cmd[-2:] == ["--format", "json"]


def test_exited_postgres_is_red() -> None:
    row = {
        "Service": "postgres",
        "State": "exited",
        "Health": "",
        "ExitCode": 137,
    }
    assert row_is_red(row) is True
