#!/usr/bin/env python3
"""Wave E hang-approval smoke — member hang → admin inbox → approve → resume.

Usage:
  Terminal 1: APP_ENV=dev make run
  Terminal 2: uv run python scripts/smoke_wave_e.py
"""

from __future__ import annotations

import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT", "90"))
PASSWORD = "password123"


def _ok(name: str) -> None:
    print(f"PASS  {name}")


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
    print(f"FAIL  health: {last}")
    raise SystemExit(1)


def pick_hang_capability(caps: list[dict]) -> dict | None:
    """可见但 member(user) 默认无权：非 chat:*；禁纯 model/LLM。"""
    for c in caps:
        perm = (c.get("permission") or "").strip()
        cid = str(c.get("id") or "")
        kind = str(c.get("kind") or "")
        if not perm or perm.startswith("chat:"):
            continue
        if kind == "model" or cid.startswith("model:"):
            continue
        return c
    return None


def seed_hang_capability(cap_id: str) -> None:
    """Insert kb:read tool into DB so member can see but not invoke."""
    from datetime import datetime

    from backend.database.pgvector_session import Capability, get_pg_session

    sf = get_pg_session()
    with sf.Session() as session:
        row = session.query(Capability).filter(Capability.id == cap_id).one_or_none()
        if row is None:
            session.add(
                Capability(
                    id=cap_id,
                    tenant_id="*",
                    name="Smoke Hang KB Tool",
                    kind="tool",
                    provider="nexusai",
                    spec={
                        "governance": True,
                        "leaf": True,
                        "executor": "rag",
                    },
                    status="enabled",
                    cost_model={},
                    permission="kb:read",
                    param_spec={
                        "query": {
                            "type": "string",
                            "required": True,
                            "description": "smoke hang probe",
                        }
                    },
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
        else:
            row.permission = "kb:read"
            row.status = "enabled"
            row.spec = {"governance": True, "leaf": True, "executor": "rag"}
            row.param_spec = {
                "query": {"type": "string", "required": True}
            }
            row.updated_at = datetime.utcnow()
        session.commit()


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    admin_user = f"smoke_e_admin_{suffix}"
    member_user = f"smoke_e_member_{suffix}"
    other_mgr = f"smoke_e_othermgr_{suffix}"
    hang_cap_id = f"smoke-hang-{suffix}"
    failed = 0

    def step(name: str, cond: bool, detail: str = "") -> None:
        nonlocal failed
        if cond:
            _ok(name)
        else:
            print(f"FAIL  {name}: {detail}")
            failed += 1

    seed_hang_capability(hang_cap_id)

    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as client:
        wait_health(client)

        def register(username: str, role: str) -> str:
            r = client.post(
                "/api/auth/register",
                json={"username": username, "password": PASSWORD, "role": role},
            )
            if r.status_code != 200:
                return ""
            return str(r.json().get("access_token") or "")

        admin_tok = register(admin_user, "tenant_admin")
        step("register_admin", bool(admin_tok))
        member_tok = register(member_user, "user")
        step("register_member", bool(member_tok))
        other_tok = register(other_mgr, "user")
        step("register_other_mgr", bool(other_tok))
        ha = {"Authorization": f"Bearer {admin_tok}"}
        hm = {"Authorization": f"Bearer {member_tok}"}
        ho = {"Authorization": f"Bearer {other_tok}"}

        r = client.post("/api/capabilities/reload", headers=ha)
        step("reload_capabilities", r.status_code == 200, r.text[:200])

        caps = client.get("/api/capabilities", headers=ha).json().get("items", [])
        hang_cap = next((c for c in caps if c.get("id") == hang_cap_id), None)
        if hang_cap is None:
            hang_cap = pick_hang_capability(caps)
        step("hang_cap_found", hang_cap is not None, f"id={hang_cap_id} n={len(caps)}")
        if not hang_cap:
            raise SystemExit(1)

        r = client.post("/api/org/units", headers=ha, json={"name": f"smoke-e-{suffix}"})
        step("create_org_unit", r.status_code == 200, r.text[:200])
        ou = r.json().get("id") if r.status_code == 200 else None

        r = client.post(
            "/api/org/units",
            headers=ha,
            json={"name": f"smoke-e-sib-{suffix}"},
        )
        sib = r.json().get("id") if r.status_code == 200 else None
        step("create_sibling_org", bool(sib), r.text[:200])

        for uid, roles, unit in (
            (admin_user, ["dept_manager"], ou),
            (member_user, ["member"], ou),
            (other_mgr, ["dept_manager"], sib),
        ):
            r = client.post(
                "/api/org/memberships",
                headers=ha,
                json={
                    "user_id": uid,
                    "org_unit_id": unit,
                    "is_primary": True,
                    "business_roles": roles,
                },
            )
            step(
                f"bind_{uid.split('_')[2] if '_' in uid else uid}",
                r.status_code == 200,
                r.text[:200],
            )

        params: dict = {}
        ps = hang_cap.get("param_spec") or {}
        if isinstance(ps, dict):
            if "query" in ps:
                params["query"] = f"smoke-e-{suffix}"
            elif "message" in ps:
                params["message"] = f"smoke-e-{suffix}"
            elif "input" in ps:
                params["input"] = f"smoke-e-{suffix}"

        ir = {
            "ir_schema": "1",
            "nodes": [
                {
                    "node_id": "n1",
                    "capability_id": hang_cap["id"],
                    "params": params,
                    "requestable": "true",
                    "approval_note": f"smoke E need {hang_cap.get('permission')}",
                }
            ],
            "edges": [],
        }
        r = client.post(
            "/api/workflows",
            headers=ha,
            json={"name": f"smoke-e-{suffix}", "ir": ir, "org_unit_id": ou},
        )
        step("create_draft", r.status_code == 200, r.text[:300])
        wid = r.json().get("id") if r.status_code == 200 else ""
        rev = int(r.json().get("revision", 0)) if r.status_code == 200 else 0
        r = client.post(
            f"/api/workflows/{wid}/publish",
            headers=ha,
            json={"base_revision": rev},
        )
        step("publish", r.status_code == 200, r.text[:300])

        r = client.post(f"/api/workflows/{wid}/runs", headers=hm)
        step("member_start_run", r.status_code == 200, r.text[:300])
        run_id = r.json().get("id") if r.status_code == 200 else ""

        status = "pending"
        deadline = time.time() + 60
        while time.time() < deadline and run_id:
            got = client.get(f"/api/runs/{run_id}", headers=hm)
            if got.status_code != 200:
                got = client.get(f"/api/runs/{run_id}", headers=ha)
            if got.status_code != 200:
                break
            status = got.json().get("status", status)
            if status in ("suspended", "succeeded", "failed"):
                break
            time.sleep(0.8)
        step("poll_suspended", status == "suspended", f"status={status}")

        detail = (
            client.get(f"/api/runs/{run_id}", headers=ha).json() if run_id else {}
        )
        step(
            "hang_visibility",
            bool(detail.get("hang_summary") or detail.get("waiting_nodes")),
            str(detail.get("hang_summary")),
        )

        inbox = client.get("/api/workflow-approvals/inbox", headers=ha)
        step("inbox_ok", inbox.status_code == 200, inbox.text[:200])
        items = inbox.json().get("items", []) if inbox.status_code == 200 else []
        match = next((i for i in items if i.get("run_id") == run_id), None)
        step("inbox_has_request", match is not None, f"count={len(items)}")

        if match and other_tok:
            bad = client.post(
                f"/api/workflow-approvals/{match['id']}/approve",
                headers=ho,
                json={},
            )
            step(
                "other_dept_denied",
                bad.status_code in (403, 404),
                f"status={bad.status_code} {bad.text[:120]}",
            )
        else:
            step("other_dept_denied", False, "no_match_or_token")

        if match:
            ap = client.post(
                f"/api/workflow-approvals/{match['id']}/approve",
                headers=ha,
                json={"reason": "smoke-e"},
            )
            step("approve", ap.status_code == 200, ap.text[:300])
        else:
            step("approve", False, "no_request")

        status2 = status
        deadline = time.time() + 120
        while time.time() < deadline and run_id:
            got = client.get(f"/api/runs/{run_id}", headers=ha)
            if got.status_code != 200:
                break
            status2 = got.json().get("status", status2)
            if status2 in ("succeeded", "failed"):
                break
            time.sleep(0.8)
        step("resume_succeeded", status2 == "succeeded", f"status={status2}")

    if failed:
        print(f"\nRESULT  {failed} failed")
        raise SystemExit(1)
    print("\nRESULT  ALL PASS")


if __name__ == "__main__":
    main()
