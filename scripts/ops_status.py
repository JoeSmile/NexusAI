#!/usr/bin/env python3
"""一眼红绿：compose ps + 可选 GET /health（Task 81 / docs/OPS.md 档 1）。"""

from __future__ import annotations

import argparse
import json
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE = ROOT / "docker-compose.prod.yml"

WATCHED = (
    "postgres",
    "redis",
    "nexusai",
    "memory-worker",
    "file-worker",
    "knowledge-worker",
    "social-worker",
    "nginx",
)
WORKERS = frozenset(
    {"memory-worker", "file-worker", "knowledge-worker", "social-worker"}
)


def compose_ps_cmd(compose_file: str | Path) -> list[str]:
    """Include stopped containers (`--all`): default `ps` only lists running."""
    return [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "ps",
        "--all",
        "--format",
        "json",
    ]


def parse_compose_ps(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            out.append(row)
    return out


def hint_for(
    service: str,
    compose_health: str,
    health_json: dict[str, Any] | None,
) -> str:
    _ = compose_health
    svc = (service or "").strip()
    db_status = _database_status(health_json)
    if svc == "nexusai" and db_status is not None and db_status != "up":
        return "先 restart postgres（不要先 restart nexusai）"
    if svc == "postgres":
        return "restart postgres"
    if svc == "redis":
        return "restart redis"
    if svc == "nexusai":
        return "restart nexusai"
    if svc in WORKERS:
        return f"restart {svc}"
    if svc == "nginx":
        return "看 deploy/ssl、frontend/dist、nginx-boot.sh 日志（不要先 restart nexusai）"
    return f"restart {svc}" if svc else ""


def worst_exit(flags: list[tuple[str, bool]]) -> int:
    return 1 if any(red for _svc, red in flags) else 0


def _database_status(health_json: dict[str, Any] | None) -> str | None:
    if not isinstance(health_json, dict):
        return None
    checks = health_json.get("checks")
    if not isinstance(checks, dict):
        return None
    db = checks.get("database")
    if not isinstance(db, dict):
        return None
    status = db.get("status")
    return str(status).lower() if status is not None else None


def _exit_code(row: dict[str, Any]) -> int | None:
    raw = row.get("ExitCode")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def row_is_red(row: dict[str, Any]) -> bool:
    service = str(row.get("Service") or "")
    state = str(row.get("State") or "")
    health = str(row.get("Health") or "")
    code = _exit_code(row)
    if service == "migrate":
        return code not in (None, 0)
    if health.lower() == "unhealthy":
        return True
    if "exit" in state.lower():
        return (code if code is not None else 1) != 0
    return False


def fetch_health(
    url: str, timeout: float
) -> tuple[int | None, dict[str, Any] | None, str | None]:
    ctx = ssl._create_unverified_context() if url.lower().startswith("https") else None
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            code = int(getattr(resp, "status", None) or resp.getcode())
            body = resp.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            return code, None, "health body is not JSON"
        return code, payload if isinstance(payload, dict) else None, None
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        payload: dict[str, Any] | None = None
        if body:
            try:
                loaded = json.loads(body)
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                payload = None
        return int(exc.code), payload, None
    except (URLError, OSError, TimeoutError, ValueError) as exc:
        return None, None, str(exc)


def _health_probe_red(
    http_status: int | None,
    health_json: dict[str, Any] | None,
    health_err: str | None,
) -> tuple[bool, bool]:
    """Return (probe_red, database_down)."""
    if health_err:
        return True, False
    db = _database_status(health_json)
    db_down = db is not None and db != "up"
    http_bad = http_status is None or http_status != 200
    return bool(http_bad or db_down), db_down


def _print_table(lines: list[tuple[str, str, str, str]]) -> None:
    print("service\tstate\thealth\thint")
    for service, state, health, hint in lines:
        print(f"{service}\t{state}\t{health}\t{hint}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compose 服务红绿与重启建议（docs/OPS.md 档 1）"
    )
    parser.add_argument("--compose", default=str(DEFAULT_COMPOSE))
    parser.add_argument("--health-url", default="")
    parser.add_argument("--timeout", type=float, default=3.0)
    try:
        args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    compose_path = Path(args.compose)
    if not compose_path.is_file():
        print(f"compose file not found: {compose_path}", file=sys.stderr)
        return 2

    try:
        proc = subprocess.run(
            compose_ps_cmd(compose_path),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError:
        print("docker not found", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print("docker compose ps timed out", file=sys.stderr)
        return 2

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "docker compose ps failed").strip()
        print(err.splitlines()[0] if err else "docker compose ps failed", file=sys.stderr)
        return 2

    try:
        rows = parse_compose_ps(proc.stdout)
    except json.JSONDecodeError:
        print("compose ps JSON parse failed", file=sys.stderr)
        return 2

    health_json: dict[str, Any] | None = None
    probe_red = False
    db_down = False
    if args.health_url:
        http_status, health_json, health_err = fetch_health(
            str(args.health_url), float(args.timeout)
        )
        probe_red, db_down = _health_probe_red(http_status, health_json, health_err)
        if health_err:
            print(health_err, file=sys.stderr)

    by_svc = {str(row.get("Service") or ""): row for row in rows}
    flags: list[tuple[str, bool]] = []
    lines: list[tuple[str, str, str, str]] = []
    for svc in WATCHED:
        row = by_svc.get(svc)
        if row is None:
            continue
        state = str(row.get("State") or "")
        health = str(row.get("Health") or "")
        red = row_is_red(row)
        if svc == "postgres" and db_down:
            red = True
        if svc == "nexusai" and probe_red:
            red = True
        if svc == "nginx" and not health:
            health_col = "no-healthcheck"
        else:
            health_col = health or "-"
        hint = hint_for(svc, health, health_json if red else None) if red else ""
        flags.append((svc, red))
        lines.append((svc, state or "-", health_col, hint))

    migrate = by_svc.get("migrate")
    if migrate is not None:
        red = row_is_red(migrate)
        flags.append(("migrate", red))
        lines.append(
            (
                "migrate",
                str(migrate.get("State") or "-"),
                str(migrate.get("Health") or "-"),
                "migrate failed" if red else "",
            )
        )

    if probe_red:
        flags.append(("health", True))

    _print_table(lines)
    return worst_exit(flags)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
