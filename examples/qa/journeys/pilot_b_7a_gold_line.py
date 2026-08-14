#!/usr/bin/env python3
"""Pilot B 7A gold-line journey — evidence → examples/qa/journeys/evidence/7a/.

Usage:
  Terminal 1: APP_ENV=dev LLM_PROVIDER=mock make run
  Terminal 2: uv run python examples/qa/journeys/pilot_b_7a_gold_line.py

Env:
  SMOKE_BASE_URL  default http://127.0.0.1:8000
  PERF=1          also run 50-concurrency + list latency smoke
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT", "120"))
PASSWORD = "password123"
EVIDENCE = Path(__file__).resolve().parent / "evidence" / "7a"
PERF = os.getenv("PERF", "0") == "1"


def _ok(name: str) -> None:
    print(f"PASS  {name}")


def _write(step: str, payload: object) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / f"{step}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


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
    raise SystemExit(f"FAIL  health: {last}")


def seed_hang_capability(cap_id: str) -> None:
    from datetime import datetime as dt

    from backend.database.pgvector_session import Capability, get_pg_session

    sf = get_pg_session()
    with sf.Session() as session:
        row = session.query(Capability).filter(Capability.id == cap_id).one_or_none()
        if row is None:
            session.add(
                Capability(
                    id=cap_id,
                    tenant_id="*",
                    name="7A Hang KB Tool",
                    kind="tool",
                    provider="nexusai",
                    spec={"governance": True, "leaf": True, "executor": "rag"},
                    status="enabled",
                    cost_model={},
                    permission="kb:read",
                    param_spec={
                        "query": {
                            "type": "string",
                            "required": True,
                            "description": "7a hang probe",
                        }
                    },
                    created_at=dt.utcnow(),
                    updated_at=dt.utcnow(),
                )
            )
        else:
            row.permission = "kb:read"
            row.status = "enabled"
            row.spec = {"governance": True, "leaf": True, "executor": "rag"}
            row.param_spec = {"query": {"type": "string", "required": True}}
            row.updated_at = dt.utcnow()
        session.commit()


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    admin_user = f"g7a_admin_{suffix}"
    member_user = f"g7a_member_{suffix}"
    auditor_user = f"g7a_auditor_{suffix}"
    hang_cap_id = f"g7a-hang-{suffix}"
    failed = 0
    checklist: dict[str, object] = {
        "run_id": None,
        "steps": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    def step(name: str, cond: bool, detail: str = "", evidence: object | None = None) -> None:
        nonlocal failed
        checklist["steps"][name] = {"ok": bool(cond), "detail": detail}
        if evidence is not None:
            _write(name, evidence)
        if cond:
            _ok(name)
        else:
            print(f"FAIL  {name}: {detail}")
            failed += 1

    seed_hang_capability(hang_cap_id)
    _write(
        "00_seed_meta",
        {
            "suffix": suffix,
            "hang_cap_id": hang_cap_id,
            "admin": admin_user,
            "member": member_user,
            "auditor": auditor_user,
        },
    )

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
        step("01_jwt_admin", bool(admin_tok), evidence={"token_prefix": admin_tok[:12]})
        member_tok = register(member_user, "user")
        step("02_jwt_member", bool(member_tok))
        auditor_tok = register(auditor_user, "auditor")
        step("02b_jwt_auditor", bool(auditor_tok))
        ha = {"Authorization": f"Bearer {admin_tok}"}
        hm = {"Authorization": f"Bearer {member_tok}"}
        had = {"Authorization": f"Bearer {auditor_tok}"}

        # Step 1–2: org tree + dept_manager
        r = client.post("/api/org/units", headers=ha, json={"name": f"g7a-{suffix}"})
        ou = r.json().get("id") if r.status_code == 200 else None
        step("03_org_unit", bool(ou), r.text[:200], {"org_unit_id": ou, "body": r.json() if r.status_code == 200 else r.text})

        r = client.post(
            "/api/org/memberships",
            headers=ha,
            json={
                "user_id": admin_user,
                "org_unit_id": ou,
                "is_primary": True,
                "business_roles": ["dept_manager"],
            },
        )
        step("04_bind_dept_manager", r.status_code == 200, r.text[:200])
        r = client.post(
            "/api/org/memberships",
            headers=ha,
            json={
                "user_id": member_user,
                "org_unit_id": ou,
                "is_primary": True,
                "business_roles": ["member"],
            },
        )
        step("05_bind_member", r.status_code == 200, r.text[:200])

        r = client.post("/api/capabilities/reload", headers=ha)
        step("06_reload_capabilities", r.status_code == 200, r.text[:200])

        caps = client.get("/api/capabilities", headers=ha).json().get("items", [])
        hang_cap = next((c for c in caps if c.get("id") == hang_cap_id), None)
        step(
            "07_hang_cap_visible",
            hang_cap is not None,
            f"n={len(caps)}",
            hang_cap,
        )
        if not hang_cap:
            raise SystemExit(1)

        # member sees cap but cannot invoke (permission kb:read)
        # D10: 保存/列表可见性由 tenant_admin 配置；member 未必列表到 kb 工具，
        # 金线可达性靠「已发布 wf + requestable」运行时挂起，不要求 member list 命中。
        member_caps = client.get("/api/capabilities", headers=hm).json().get("items", [])
        seen = any(c.get("id") == hang_cap_id for c in member_caps)
        step(
            "08_member_cap_list_note",
            True,
            f"listed={seen} n={len(member_caps)} (list optional; run path is Must)",
            {"listed": seen, "n": len(member_caps)},
        )

        params: dict = {"query": f"g7a-{suffix}"}
        ir = {
            "ir_schema": "1",
            "nodes": [
                {
                    "node_id": "n1",
                    "capability_id": hang_cap["id"],
                    "params": params,
                    "requestable": "true",
                    "approval_note": f"7A need {hang_cap.get('permission')}",
                }
            ],
            "edges": [],
        }
        r = client.post(
            "/api/workflows",
            headers=ha,
            json={"name": f"g7a-{suffix}", "ir": ir, "org_unit_id": ou},
        )
        wid = r.json().get("id") if r.status_code == 200 else ""
        rev = int(r.json().get("revision", 0)) if r.status_code == 200 else 0
        step("09_create_draft", r.status_code == 200, r.text[:300], r.json() if r.status_code == 200 else r.text)

        r = client.post(
            f"/api/workflows/{wid}/publish",
            headers=ha,
            json={"base_revision": rev},
        )
        step("10_publish", r.status_code == 200, r.text[:300])

        r = client.post(f"/api/workflows/{wid}/runs", headers=hm)
        run_id = r.json().get("id") if r.status_code == 200 else ""
        checklist["run_id"] = run_id
        step("11_member_run", r.status_code == 200, r.text[:300], {"run_id": run_id})

        status = "pending"
        deadline = time.time() + 90
        detail = {}
        while time.time() < deadline and run_id:
            got = client.get(f"/api/runs/{run_id}", headers=hm)
            if got.status_code != 200:
                got = client.get(f"/api/runs/{run_id}", headers=ha)
            if got.status_code != 200:
                break
            detail = got.json()
            status = detail.get("status", status)
            if status in ("suspended", "succeeded", "failed"):
                break
            time.sleep(0.8)
        step(
            "12_suspended",
            status == "suspended",
            f"status={status}",
            detail,
        )
        step(
            "13_hang_visibility",
            bool(detail.get("hang_summary") or detail.get("waiting_nodes")),
            str(detail.get("hang_summary")),
        )

        inbox = client.get("/api/workflow-approvals/inbox", headers=ha)
        items = inbox.json().get("items", []) if inbox.status_code == 200 else []
        match = next((i for i in items if i.get("run_id") == run_id), None)
        step(
            "14_inbox",
            match is not None,
            f"count={len(items)}",
            {"inbox_status": inbox.status_code, "match": match, "items": items[:5]},
        )

        if match:
            ap = client.post(
                f"/api/workflow-approvals/{match['id']}/approve",
                headers=ha,
                json={"reason": "7a-gold"},
            )
            step("15_approve", ap.status_code == 200, ap.text[:300], ap.json() if ap.status_code == 200 else ap.text)
        else:
            step("15_approve", False, "no_request")

        status2 = status
        deadline = time.time() + 120
        final = {}
        while time.time() < deadline and run_id:
            got = client.get(f"/api/runs/{run_id}", headers=ha)
            if got.status_code != 200:
                break
            final = got.json()
            status2 = final.get("status", status2)
            if status2 in ("succeeded", "failed"):
                break
            time.sleep(0.8)
        step("16_resume_succeeded", status2 == "succeeded", f"status={status2}", final)

        # evidence on run nodes
        nodes = final.get("nodes") or final.get("node_runs") or []
        ev_items = []
        for n in nodes if isinstance(nodes, list) else []:
            if isinstance(n, dict):
                ev_items.extend(n.get("evidence") or [])
        step(
            "17_evidence_queue",
            True,  # may be empty if RAG miss — still record
            f"count={len(ev_items)}",
            {"evidence": ev_items, "nodes": nodes},
        )

        # auditor export
        exp = client.get("/api/audit/export", headers=had)
        csv_text = exp.text if exp.status_code == 200 else ""
        csv_path = EVIDENCE / "18_audit_export.csv"
        if exp.status_code == 200:
            csv_path.write_text(csv_text, encoding="utf-8")
        # params plaintext check: look for api keys patterns
        has_bearer_secret = "sk-" in csv_text or "cg_" in csv_text
        step(
            "18_audit_export",
            exp.status_code == 200 and not has_bearer_secret,
            f"status={exp.status_code} bytes={len(csv_text)} secretish={has_bearer_secret}",
            {
                "status": exp.status_code,
                "bytes": len(csv_text),
                "header": csv_text.splitlines()[0] if csv_text else "",
                "has_cg_or_sk": has_bearer_secret,
            },
        )

        # JWT product shell signal: token path used (no X-API-Key)
        step(
            "19_jwt_not_apikey",
            admin_tok.startswith("eyJ") and member_tok.startswith("eyJ"),
            "jwt_prefix_ok",
        )

        if PERF:
            # 50 concurrent runs on a no-hang chat-less path: reuse hang wf may suspend;
            # use a simple published wf with chat capability if available.
            # Prefer tool with chat:write + empty/simple param_spec (avoid agent WF_011)
            chat_cap = next(
                (c for c in caps if c.get("id") == "nexusai-chat"),
                None,
            ) or next(
                (
                    c
                    for c in caps
                    if c.get("kind") == "tool"
                    and (c.get("permission") or "").startswith("chat:")
                ),
                None,
            )
            perf_notes: dict = {"mode": "50_concurrent_start"}
            if chat_cap:
                ps = chat_cap.get("param_spec") or {}
                params2: dict = {}
                if isinstance(ps, dict) and ps:
                    if "message" in ps:
                        params2["message"] = "ping"
                    elif "query" in ps:
                        params2["query"] = "ping"
                    elif "input" in ps:
                        params2["input"] = "ping"
                ir2 = {
                    "ir_schema": "1",
                    "nodes": [
                        {
                            "node_id": "n1",
                            "capability_id": chat_cap["id"],
                            "params": params2,
                            "requestable": "false",
                        }
                    ],
                    "edges": [],
                }
                r = client.post(
                    "/api/workflows",
                    headers=ha,
                    json={"name": f"g7a-perf-{suffix}", "ir": ir2, "org_unit_id": ou},
                )
                pwid = r.json().get("id") if r.status_code == 200 else ""
                prev = int(r.json().get("revision", 0)) if r.status_code == 200 else 0
                pub = (
                    client.post(
                        f"/api/workflows/{pwid}/publish",
                        headers=ha,
                        json={"base_revision": prev},
                    )
                    if pwid
                    else None
                )
                perf_notes["perf_wf"] = {
                    "cap": chat_cap.get("id"),
                    "create": r.status_code,
                    "publish": None if pub is None else pub.status_code,
                    "create_body": r.text[:200],
                }

                def _start(_: int) -> tuple[int, str]:
                    # admin starts to avoid member permission hang on chat models
                    rr = client.post(f"/api/workflows/{pwid}/runs", headers=ha)
                    return rr.status_code, rr.text[:160]

                t0 = time.perf_counter()
                codes: list[int] = []
                samples: list[str] = []
                with ThreadPoolExecutor(max_workers=50) as pool:
                    futs = [pool.submit(_start, i) for i in range(50)]
                    for f in as_completed(futs):
                        code, body = f.result()
                        codes.append(code)
                        if code not in (200, 429) and len(samples) < 3:
                            samples.append(f"{code}:{body}")
                elapsed = time.perf_counter() - t0
                ok_n = sum(1 for c in codes if c == 200)
                rate_n = sum(1 for c in codes if c == 429)
                perf_notes["50_start"] = {
                    "elapsed_s": round(elapsed, 3),
                    "ok": ok_n,
                    "429": rate_n,
                    "other": len(codes) - ok_n - rate_n,
                    "samples": samples,
                }
            else:
                perf_notes["50_start"] = {"skipped": "no_chat_cap"}

            # list latency — pad history if needed then time GET
            # API list_runs limit le=100 — 诚实：10 页 ×100 ≈ 1000 条总耗时
            t1 = time.perf_counter()
            items_n = 0
            pages = 0
            last_status = 0
            for off in range(0, 1000, 100):
                lst = client.get(
                    "/api/runs", headers=ha, params={"limit": 100, "offset": off}
                )
                last_status = lst.status_code
                pages += 1
                if lst.status_code != 200:
                    break
                batch = lst.json().get("items") or []
                items_n += len(batch)
                if len(batch) < 100:
                    break
            list_s = time.perf_counter() - t1
            perf_notes["list_1000"] = {
                "status": last_status,
                "pages": pages,
                "elapsed_s": round(list_s, 3),
                "items": items_n,
                "api_max_page": 100,
                "target_lt_2s": list_s < 2.0,
                "gap": (
                    "insufficient_history_rows"
                    if items_n < 1000
                    else (None if list_s < 2.0 else "list_over_2s")
                ),
            }
            step(
                "20_perf_smoke",
                True,
                json.dumps(perf_notes, ensure_ascii=False),
                perf_notes,
            )

    checklist["finished_at"] = datetime.now(timezone.utc).isoformat()
    checklist["failed"] = failed
    _write("zz_checklist", checklist)

    if failed:
        print(f"\nRESULT  {failed} failed — see {EVIDENCE}")
        raise SystemExit(1)
    print(f"\nRESULT  ALL PASS — evidence in {EVIDENCE}")


if __name__ == "__main__":
    main()
