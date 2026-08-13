#!/usr/bin/env python3
"""Wave C workflow definition smoke — httpx against local API.

Usage:
  Terminal 1: APP_ENV=dev make run
  Terminal 2: uv run python scripts/smoke_wave_c.py

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
    print(f"FAIL  health: API not ready ({last})")
    raise SystemExit(1)


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    admin_user = f"smoke_c_admin_{suffix}"
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

        r = client.post(
            "/api/auth/register",
            json={
                "username": admin_user,
                "password": PASSWORD,
                "role": "tenant_admin",
            },
        )
        step("register_admin", r.status_code == 200, r.text[:200])
        token = r.json().get("access_token", "") if r.status_code == 200 else ""
        h = {"Authorization": f"Bearer {token}"}

        r = client.post(
            "/api/workflows",
            headers=h,
            json={
                "name": f"smoke-c-{suffix}",
                "ir": {"ir_schema": "1", "nodes": [], "edges": []},
            },
        )
        step("create_draft", r.status_code == 200, r.text[:300])
        wf = r.json() if r.status_code == 200 else {}
        wid = wf.get("id", "")
        rev = int(wf.get("revision", -1))

        # Discover a capability with param_spec (rag-ask preferred)
        caps = client.get("/api/capabilities", headers=h)
        step("list_capabilities", caps.status_code == 200, caps.text[:200])
        items = caps.json().get("items", []) if caps.status_code == 200 else []
        rag = next((c for c in items if c.get("id") == "rag-ask"), None)
        chat = next((c for c in items if c.get("id") == "nexusai-chat"), None)
        # Fallback: any with param_spec / any tool
        if rag is None:
            rag = next((c for c in items if c.get("param_spec")), None) or (
                items[0] if items else None
            )
        if chat is None:
            chat = next((c for c in items if c.get("id") != (rag or {}).get("id")), None)

        nodes = []
        if rag:
            ps = rag.get("param_spec") or {}
            params = {}
            if "query" in ps:
                params["query"] = "smoke query"
            elif "message" in ps:
                params["message"] = "smoke msg"
            nodes.append(
                {
                    "node_id": "n1",
                    "capability_id": rag["id"],
                    "params": params,
                }
            )
        if chat:
            ps = chat.get("param_spec") or {}
            params = {}
            if "message" in ps:
                params["message"] = "hi"
            elif "query" in ps:
                params["query"] = "hi"
            nodes.append(
                {
                    "node_id": "n2",
                    "capability_id": chat["id"],
                    "params": params,
                }
            )
        step("build_nodes", len(nodes) >= 1, f"caps={len(items)}")

        r = client.patch(
            f"/api/workflows/{wid}",
            headers=h,
            json={
                "base_revision": rev,
                "ir": {"ir_schema": "1", "nodes": nodes, "edges": []},
            },
        )
        step("patch_save", r.status_code == 200, r.text[:300])
        rev2 = int(r.json().get("revision", -1)) if r.status_code == 200 else rev

        # Concurrent optimistic lock: two PATCH with same base_revision
        r_a = client.patch(
            f"/api/workflows/{wid}",
            headers=h,
            json={"base_revision": rev2, "name": f"smoke-c-{suffix}-a"},
        )
        r_b = client.patch(
            f"/api/workflows/{wid}",
            headers=h,
            json={"base_revision": rev2, "name": f"smoke-c-{suffix}-b"},
        )
        codes = sorted([r_a.status_code, r_b.status_code])
        step("double_patch_one_409", codes == [200, 409], f"codes={codes}")
        # Refresh revision from winner
        got = client.get(f"/api/workflows/{wid}", headers=h)
        rev3 = int(got.json().get("revision", -1)) if got.status_code == 200 else -1

        r = client.post(
            f"/api/workflows/{wid}/publish",
            headers=h,
            json={"base_revision": rev3},
        )
        step("publish", r.status_code == 200 and r.json().get("status") == "published", r.text[:300])
        pub_rev = int(r.json().get("revision", -1)) if r.status_code == 200 else -1

        listed = client.get("/api/workflows", headers=h)
        ids = [i["id"] for i in listed.json().get("items", [])] if listed.status_code == 200 else []
        step("list_sees_published", wid in ids, listed.text[:200])

        bad = client.patch(
            f"/api/workflows/{wid}",
            headers=h,
            json={"base_revision": pub_rev, "name": "nope"},
        )
        step("patch_published_409", bad.status_code == 409, bad.text[:200])

        fork = client.post(f"/api/workflows/{wid}/fork-draft", headers=h)
        step(
            "fork_draft",
            fork.status_code == 200 and fork.json().get("status") == "draft",
            fork.text[:300],
        )
        fork_id = fork.json().get("id") if fork.status_code == 200 else None
        step("fork_new_id", bool(fork_id) and fork_id != wid, str(fork_id))

    if failed:
        print(f"\n{failed} step(s) failed")
        raise SystemExit(1)
    print("\nALL PASS")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
