#!/usr/bin/env python3
"""Wave D workflow run smoke — publish → run → poll → evidence → history.

Usage:
  Terminal 1: APP_ENV=dev make run
  Terminal 2: uv run python scripts/smoke_wave_d.py
"""

from __future__ import annotations

import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT", "60"))
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


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    admin_user = f"smoke_d_admin_{suffix}"
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

        # Primary org required for run.org_unit_id
        r = client.post("/api/org/units", headers=h, json={"name": f"smoke-d-{suffix}"})
        step("create_org_unit", r.status_code == 200, r.text[:200])
        ou = r.json().get("id") if r.status_code == 200 else None
        r = client.post(
            "/api/org/memberships",
            headers=h,
            json={
                "user_id": admin_user,
                "org_unit_id": ou,
                "is_primary": True,
                "business_roles": ["member"],
            },
        )
        step("bind_primary_org", r.status_code == 200, r.text[:200])

        # 真实 KB sources → evidence（禁止 answer 合成）
        marker = f"SMOKE_D_EVIDENCE_MARKER_{suffix}"
        r = client.post(
            "/api/rag/upload",
            headers=h,
            files={
                "file": (
                    f"smoke-d-{suffix}.txt",
                    f"{marker}\nNexusAI smoke wave D knowledge chunk.\n".encode(),
                    "text/plain",
                )
            },
            data={"category": "general"},
        )
        step("rag_upload_kb", r.status_code == 200, r.text[:300])

        # IR with RAG node querying the uploaded marker
        ir = {
            "ir_schema": "1",
            "nodes": [
                {
                    "node_id": "n1",
                    "capability_id": "rag-ask",
                    "params": {"query": marker},
                }
            ],
            "edges": [],
        }
        r = client.post(
            "/api/workflows",
            headers=h,
            json={"name": f"smoke-d-{suffix}", "ir": ir, "org_unit_id": ou},
        )
        step("create_draft", r.status_code == 200, r.text[:300])
        wid = r.json().get("id") if r.status_code == 200 else ""
        rev = int(r.json().get("revision", 0)) if r.status_code == 200 else 0

        # If create rejected params (rag not seeded), patch after listing caps
        if r.status_code != 200:
            caps = client.get("/api/capabilities", headers=h).json().get("items", [])
            rag = next((c for c in caps if c.get("id") == "rag-ask"), None) or (
                caps[0] if caps else None
            )
            params = {}
            if rag and rag.get("param_spec"):
                if "query" in rag["param_spec"]:
                    params["query"] = "smoke"
                elif "message" in rag["param_spec"]:
                    params["message"] = "smoke"
            r = client.post(
                "/api/workflows",
                headers=h,
                json={
                    "name": f"smoke-d-{suffix}",
                    "ir": {
                        "nodes": [
                            {
                                "node_id": "n1",
                                "capability_id": rag["id"] if rag else "rag-ask",
                                "params": params,
                            }
                        ]
                    },
                    "org_unit_id": ou,
                },
            )
            step("create_draft_retry", r.status_code == 200, r.text[:300])
            wid = r.json().get("id") if r.status_code == 200 else ""
            rev = int(r.json().get("revision", 0)) if r.status_code == 200 else 0

        r = client.post(
            f"/api/workflows/{wid}/publish",
            headers=h,
            json={"base_revision": rev},
        )
        step("publish", r.status_code == 200, r.text[:300])

        r = client.post(f"/api/workflows/{wid}/runs", headers=h)
        step("start_run", r.status_code == 200, r.text[:300])
        run_id = r.json().get("id") if r.status_code == 200 else ""

        status = "pending"
        deadline = time.time() + 90
        while time.time() < deadline:
            got = client.get(f"/api/runs/{run_id}", headers=h)
            if got.status_code != 200:
                break
            status = got.json().get("status", status)
            if status in ("succeeded", "failed"):
                break
            time.sleep(1)
        step("poll_terminal", status in ("succeeded", "failed"), f"status={status}")
        step("run_succeeded", status == "succeeded", f"status={status}")

        nodes = client.get(f"/api/runs/{run_id}/nodes", headers=h)
        step("nodes_ok", nodes.status_code == 200, nodes.text[:200])
        items = nodes.json().get("items", []) if nodes.status_code == 200 else []
        evidence = []
        for it in items:
            evidence.extend(it.get("evidence") or [])
        step("evidence_nonempty", len(evidence) > 0, f"count={len(evidence)}")

        hist = client.get("/api/runs?limit=20", headers=h)
        ids = [i["id"] for i in hist.json().get("items", [])] if hist.status_code == 200 else []
        step("history_contains_run", run_id in ids, hist.text[:200])

    if failed:
        print(f"\n{failed} step(s) failed")
        raise SystemExit(1)
    print("\nALL PASS")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
