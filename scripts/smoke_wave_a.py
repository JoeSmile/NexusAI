#!/usr/bin/env python3
"""Wave A auth loop smoke — httpx against local API.

Usage:
  Terminal 1: APP_ENV=dev make run
  Terminal 2: uv run python scripts/smoke_wave_a.py

Exit 0 iff all steps PASS.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta, timezone

# Project root on sys.path for `uv run python scripts/smoke_wave_a.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import jwt

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-wave-a-jwt-secret-min-32b")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT", "30"))


def _ok(name: str) -> None:
    print(f"PASS  {name}")


def _fail(name: str, detail: str) -> None:
    print(f"FAIL  {name}: {detail}")
    raise SystemExit(1)


def wait_health(client: httpx.Client, *, timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            r = client.get("/health")
            if r.status_code == 200:
                _ok("health")
                return
            last = f"status={r.status_code}"
        except Exception as e:
            last = str(e)
        time.sleep(0.5)
    _fail("health", f"API not ready within {timeout_s}s ({last})")


def main() -> None:
    user = f"smoke_a_{uuid.uuid4().hex[:10]}"
    password = "password123"
    failed = 0

    def step(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failed
        if cond:
            _ok(name)
        else:
            print(f"FAIL  {name}: {detail}")
            failed += 1

    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as client:
        wait_health(client)

        # 1) register → JWT, no api_key
        r = client.post(
            "/api/auth/register",
            json={"username": user, "password": password, "role": "user"},
        )
        step(
            "register_jwt",
            r.status_code == 200
            and "access_token" in r.json()
            and "api_key" not in r.json(),
            f"status={r.status_code} body={r.text[:200]}",
        )
        reg = r.json() if r.status_code == 200 else {}
        token = reg.get("access_token", "")

        # Optional: DB assert no new api_keys for this user from register
        try:
            from sqlalchemy import text

            from packages.database.pgvector_session import get_pg_session

            sf = get_pg_session()
            with sf.Session() as session:
                row = session.execute(
                    text(
                        "SELECT count(*) FROM api_keys WHERE user_id=:u AND description LIKE 'register:%'"
                    ),
                    {"u": user},
                ).fetchone()
            step(
                "register_no_api_keys_row",
                row is not None and int(row[0]) == 0,
                f"count={row}",
            )
        except Exception as e:
            print(f"SKIP  register_no_api_keys_row: {e}")

        # 2) login → JWT
        r = client.post(
            "/api/auth/login",
            json={"username": user, "password": password},
        )
        step(
            "login_jwt",
            r.status_code == 200
            and "access_token" in r.json()
            and "api_key" not in r.json(),
            f"status={r.status_code} body={r.text[:200]}",
        )
        if r.status_code == 200:
            token = r.json()["access_token"]

        headers_b = {"Authorization": f"Bearer {token}"}

        # 3) Bearer → capabilities
        r = client.get("/api/capabilities", headers=headers_b)
        step(
            "bearer_capabilities",
            r.status_code == 200,
            f"status={r.status_code} body={r.text[:200]}",
        )

        # 4) Bearer → require_permission endpoint (memory list)
        r = client.get(f"/memory/users/{user}/memories", headers=headers_b)
        step(
            "bearer_require_permission",
            r.status_code == 200,
            f"status={r.status_code} body={r.text[:200]}",
        )

        # 5) failure paths
        r = client.post(
            "/api/auth/login",
            json={"username": user, "password": "wrong-password-xx"},
        )
        step("wrong_password_401", r.status_code == 401, f"status={r.status_code}")

        r = client.get("/api/capabilities")
        step("no_token_401", r.status_code == 401, f"status={r.status_code}")

        expired = jwt.encode(
            {
                "sub": user,
                "tid": "acme",
                "role": "user",
                "jti": str(uuid.uuid4()),
                "exp": datetime.now(UTC) - timedelta(seconds=10),
            },
            JWT_SECRET,
            algorithm="HS256",
        )
        r = client.get(
            "/api/capabilities",
            headers={"Authorization": f"Bearer {expired}"},
        )
        step("expired_token_401", r.status_code == 401, f"status={r.status_code}")

        # 6) seed-style X-API-Key still works
        raw_key = f"cg_{secrets.token_hex(16)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        try:
            from sqlalchemy import text

            from packages.database.pgvector_session import get_pg_session

            sf = get_pg_session()
            with sf.Session() as session:
                session.execute(
                    text(
                        """
                        INSERT INTO api_keys
                            (tenant_id, user_id, key_hash, key_prefix, role,
                             description, created_by, is_active, created_at)
                        VALUES
                            ('acme', :uid, :hash, :prefix, 'user',
                             'smoke_wave_a', 'smoke', true, now())
                        """
                    ),
                    {
                        "uid": user,
                        "hash": key_hash,
                        "prefix": raw_key[:8],
                    },
                )
                session.commit()
            r = client.get("/api/capabilities", headers={"X-API-Key": raw_key})
            step(
                "legacy_api_key_200",
                r.status_code == 200,
                f"status={r.status_code} body={r.text[:200]}",
            )
        except Exception as e:
            _fail("legacy_api_key_200", str(e))

    if failed:
        print(f"\nRESULT: {failed} FAILED")
        raise SystemExit(1)
    print("\nRESULT: ALL PASS")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
