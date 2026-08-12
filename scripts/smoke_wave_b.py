#!/usr/bin/env python3
"""Wave B org scope loop smoke — httpx against local API.

Usage:
  Terminal 1: APP_ENV=dev make run
  Terminal 2: uv run python scripts/smoke_wave_b.py

Exit 0 iff all steps PASS.
"""

from __future__ import annotations

import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT", "30"))
PASSWORD = "password123"


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
    suffix = uuid.uuid4().hex[:8]
    admin_user = f"smoke_b_admin_{suffix}"
    member_user = f"smoke_b_member_{suffix}"
    manager_user = f"smoke_b_mgr_{suffix}"
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

        def register(username: str, role: str) -> str:
            r = client.post(
                "/api/auth/register",
                json={
                    "username": username,
                    "password": PASSWORD,
                    "role": role,
                },
            )
            if r.status_code != 200:
                return ""
            return r.json().get("access_token", "")

        admin_tok = register(admin_user, "tenant_admin")
        step("register_admin", bool(admin_tok), "no token")
        member_tok = register(member_user, "user")
        step("register_member", bool(member_tok), "no token")
        manager_tok = register(manager_user, "user")
        step("register_manager", bool(manager_tok), "no token")

        # Resolve user_ids from JWT payload is awkward; memberships use username as user_id
        # Auth register sets user_id from username in this codebase — verify via /memberships/me after assign.
        h_admin = {"Authorization": f"Bearer {admin_tok}"}

        r = client.post(
            "/api/org/units",
            headers=h_admin,
            json={"name": "财务"},
        )
        step("create_finance", r.status_code == 200, r.text[:200])
        finance = r.json() if r.status_code == 200 else {}
        fin_id = finance.get("id", "")

        r = client.post(
            "/api/org/units",
            headers=h_admin,
            json={"name": "会计", "parent_id": fin_id},
        )
        step("create_accounting", r.status_code == 200, r.text[:200])
        acct = r.json() if r.status_code == 200 else {}
        acct_id = acct.get("id", "")

        r = client.post(
            "/api/org/units",
            headers=h_admin,
            json={"name": "人事"},
        )
        step("create_hr", r.status_code == 200, r.text[:200])
        hr = r.json() if r.status_code == 200 else {}
        hr_id = hr.get("id", "")

        # Lookup user_id: register uses generated user_id — get from login JWT claims via me
        # Use DB or decode — smoke_a uses username; check auth register returns user_id
        def user_id_from_token(tok: str) -> str:
            import jwt as pyjwt

            secret = os.getenv("JWT_SECRET", "dev-only-wave-a-jwt-secret-min-32b")
            payload = pyjwt.decode(tok, secret, algorithms=["HS256"])
            return str(payload.get("sub", ""))

        member_uid = user_id_from_token(member_tok) if member_tok else ""
        manager_uid = user_id_from_token(manager_tok) if manager_tok else ""
        step("decode_uids", bool(member_uid and manager_uid), "jwt decode failed")

        r = client.post(
            "/api/org/memberships",
            headers=h_admin,
            json={
                "user_id": member_uid,
                "org_unit_id": fin_id,
                "is_primary": True,
                "business_roles": ["member"],
            },
        )
        step("assign_member", r.status_code == 200, r.text[:200])

        r = client.post(
            "/api/org/memberships",
            headers=h_admin,
            json={
                "user_id": manager_uid,
                "org_unit_id": fin_id,
                "is_primary": True,
                "business_roles": ["dept_manager"],
            },
        )
        step("assign_manager", r.status_code == 200, r.text[:200])

        h_mgr = {"Authorization": f"Bearer {manager_tok}"}
        r = client.get("/api/org/units/tree", headers=h_mgr)
        step("manager_tree_200", r.status_code == 200, r.text[:200])
        ids = {u["id"] for u in (r.json() if r.status_code == 200 else [])}
        step(
            "manager_sees_finance_subtree",
            fin_id in ids and acct_id in ids,
            f"ids={ids}",
        )
        step("manager_hides_hr", hr_id not in ids, f"ids={ids}")

        h_mem = {"Authorization": f"Bearer {member_tok}"}
        r = client.get(f"/api/org/units/{hr_id}/memberships", headers=h_mem)
        step(
            "member_cross_dept_403",
            r.status_code == 403,
            f"status={r.status_code} body={r.text[:200]}",
        )

        # RAG: upload without primary should 400 for a fresh user — member has primary
        r = client.post(
            "/api/rag/upload",
            headers=h_mem,
            files={"file": ("note.txt", b"finance secret doc", "text/plain")},
            data={"category": "general"},
        )
        step(
            "member_rag_upload",
            r.status_code == 200 and r.json().get("org_unit_id") == fin_id,
            f"status={r.status_code} body={r.text[:300]}",
        )

        # Cross-dept ask: create hr-only user without access to finance chunks
        # Manager ask should still work; member of hr shouldn't see finance — assign someone to hr
        hr_user = f"smoke_b_hr_{suffix}"
        hr_tok = register(hr_user, "user")
        hr_uid = user_id_from_token(hr_tok) if hr_tok else ""
        client.post(
            "/api/org/memberships",
            headers=h_admin,
            json={
                "user_id": hr_uid,
                "org_unit_id": hr_id,
                "is_primary": True,
                "business_roles": ["member"],
            },
        )
        h_hr = {"Authorization": f"Bearer {hr_tok}"}
        r = client.post(
            "/api/rag/ask",
            headers=h_hr,
            json={"question": "finance secret doc", "search_k": 3},
        )
        # ask may 200 with empty/no finance sources — check sources don't include finance org
        ok_ask = r.status_code == 200
        body = r.json() if ok_ask else {}
        data = body.get("data") or body
        sources = data.get("sources") or data.get("source_documents") or []
        leaked = False
        for s in sources:
            meta = s.get("metadata") if isinstance(s, dict) else {}
            if isinstance(meta, dict) and meta.get("org_unit_id") == fin_id:
                leaked = True
        step(
            "hr_ask_no_finance_chunks",
            ok_ask and not leaked,
            f"status={r.status_code} leaked={leaked} body={str(body)[:300]}",
        )

        # No primary org upload → 400
        lone = f"smoke_b_lone_{suffix}"
        lone_tok = register(lone, "user")
        r = client.post(
            "/api/rag/upload",
            headers={"Authorization": f"Bearer {lone_tok}"},
            files={"file": ("x.txt", b"orphan", "text/plain")},
        )
        step(
            "no_primary_upload_400",
            r.status_code == 400,
            f"status={r.status_code} body={r.text[:200]}",
        )

    if failed:
        raise SystemExit(1)
    print("ALL PASS")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
