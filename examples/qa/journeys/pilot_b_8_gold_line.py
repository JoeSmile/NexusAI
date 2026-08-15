#!/usr/bin/env python3
"""Pilot B 金线 8 — 组合编排(Wave 8)API 驱动 journey → examples/qa/journeys/evidence/8/.

Usage:
  Terminal 1: APP_ENV=dev LLM_PROVIDER=mock make run
  Terminal 2: uv run python examples/qa/journeys/pilot_b_8_gold_line.py

Env:
  SMOKE_BASE_URL  default http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT", "120"))
PASSWORD = "password123"
EVIDENCE = Path(__file__).resolve().parent / "evidence" / "8"


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
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = client.get("/health")
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1.0)
    raise SystemExit("health check timed out — is the server up?")


def archive_old_gold_workflows() -> None:
    """归档历史金线 8 的 published workflow(每轮 tag 相同,match 会挑到旧 org 的)。"""
    from backend.database.pgvector_session import Workflow, get_pg_session

    sf = get_pg_session()
    with sf.Session() as session:
        rows = (
            session.query(Workflow)
            .filter(Workflow.status == "published", Workflow.name.like("g8-%"))
            .all()
        )
        for w in rows:
            w.status = "archived"
            w.updated_at = datetime.utcnow()
        session.commit()


def seed_hang_capability(cap_id: str) -> None:
    """requestable 挂起能力(kb:read):子 run 挂起 → 父 waiting_child 的触发器。"""
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
                    name="8 Gold Hang KB Tool",
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
                            "description": "gold8 hang probe",
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
    admin_user = f"g8_admin_{suffix}"
    member_user = f"g8_member_{suffix}"
    hang_cap_id = f"g8-hang-{suffix}"
    failed = 0
    checklist: dict[str, object] = {
        "run_id": None,
        "child_run_id": None,
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
    archive_old_gold_workflows()
    _write(
        "00_seed_meta",
        {
            "suffix": suffix,
            "hang_cap_id": hang_cap_id,
            "admin": admin_user,
            "member": member_user,
        },
    )

    with httpx.Client(base_url=BASE, timeout=TIMEOUT, trust_env=False) as client:
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
        ha = {"Authorization": f"Bearer {admin_tok}"}
        hm = {"Authorization": f"Bearer {member_tok}"}

        # seed 后刷新能力注册表(否则 registry 缓存看不到新 cap)
        rr = client.post("/api/capabilities/reload", headers=ha)
        step("02c_reload_registry", rr.status_code == 200, rr.text[:120])

        # 组织:admin=dept_manager, member=member(审批路由 E2 祖先链)
        r = client.post("/api/org/units", headers=ha, json={"name": f"g8-{suffix}"})
        ou = r.json().get("id") if r.status_code == 200 else None
        step("03_org_unit", bool(ou), r.text[:200], {"org_unit_id": ou})
        r = client.post(
            "/api/org/memberships",
            headers=ha,
            json={"user_id": admin_user, "org_unit_id": ou, "is_primary": True, "business_roles": ["dept_manager"]},
        )
        step("04_bind_admin_dept_manager", r.status_code == 200, r.text[:200])
        r = client.post(
            "/api/org/memberships",
            headers=ha,
            json={"user_id": member_user, "org_unit_id": ou, "is_primary": True, "business_roles": ["member"]},
        )
        step("05_bind_member", r.status_code == 200, r.text[:200])

        # 桥触发句意图预检(自适应打 tag):member token 调 /intent/analyze
        detected_intent = ""
        intent_conf = 0.0
        try:
            r = client.post(
                "/intent/analyze",
                headers=hm,
                json={"text": "帮我生成一份教育热点口播稿", "user_id": member_user},
            )
            if r.status_code == 200:
                body = r.json()
                di = (body.get("data") or {}).get("intent") or {}
                detected_intent = str(
                    body.get("intent")
                    or (body.get("result") or {}).get("intent")
                    or di.get("intent")
                    or ""
                )
                intent_conf = float(
                    body.get("confidence")
                    or (body.get("result") or {}).get("confidence")
                    or di.get("confidence")
                    or 0.0
                )
        except Exception:
            pass
        step(
            "05b_intent_probe",
            bool(detected_intent),
            f"intent={detected_intent} conf={intent_conf}",
            {"intent": detected_intent, "confidence": intent_conf},
        )

        # 1. 子 workflow(admin 建,挂起能力节点 requestable)
        child_ir = {
            "nodes": [
                {
                    "node_id": "gen",
                    "capability_id": hang_cap_id,
                    "params": {"query": "gold8"},
                    "requestable": "true",
                }
            ],
            "edges": [],
        }
        r = client.post(
            "/api/workflows",
            headers=ha,
            json={"name": f"g8-child-{suffix}", "org_unit_id": ou, "ir": child_ir},
        )
        child_wf = r.json() if r.status_code == 200 else {}
        child_wf_id = child_wf.get("id") or ""
        step("06_create_child_workflow", bool(child_wf_id), r.text[:300], child_wf)
        r = client.post(f"/api/workflows/{child_wf_id}/publish", headers=ha, json={})
        step("07_publish_child", r.status_code == 200, r.text[:200])

        # 1b. 父 workflow(kind=workflow → child)+ intent_tags(40.86 桥)
        parent_ir = {
            "nodes": [
                {
                    "node_id": "sub",
                    "kind": "workflow",
                    "workflow_id": child_wf_id,
                    "params": {},
                }
            ],
            "edges": [],
        }
        r = client.post(
            "/api/workflows",
            headers=ha,
            json={"name": f"g8-parent-{suffix}", "org_unit_id": ou, "ir": parent_ir},
        )
        parent_wf = r.json() if r.status_code == 200 else {}
        parent_wf_id = parent_wf.get("id") or ""
        step("08_create_parent_workflow", bool(parent_wf_id), r.text[:300], parent_wf)
        tag_list = list(
            dict.fromkeys(
                [detected_intent, "function", "conversation", "知识", "生成"]
                if detected_intent
                else ["function", "conversation", "知识", "生成"]
            )
        )
        r = client.post(
            f"/api/workflows/{parent_wf_id}/publish",
            headers=ha,
            json={"intent_tags": tag_list},
        )
        step("09_publish_parent_intent_tags", r.status_code == 200, r.text[:200], r.json() if r.status_code == 200 else r.text)

        # 2. member 起根 run + run_inputs
        r = client.post(
            f"/api/workflows/{parent_wf_id}/runs",
            headers=hm,
            json={"input": {"topic": "教育热点", "style": "口播"}},
        )
        started = r.json() if r.status_code == 200 else {}
        run_id = started.get("id") or started.get("run_id") or ""
        step("10_start_root_run", bool(run_id), r.text[:300], started)
        checklist["run_id"] = run_id

        # 3. 子 run 由 Runner 内部启动 → children 非空
        children: list = []
        child_run_id = ""
        for _ in range(30):
            time.sleep(0.5)
            r = client.get(f"/api/runs/{run_id}/children", headers=hm)
            if r.status_code == 200:
                children = r.json().get("items") or []
                if children:
                    child_run_id = str(children[0].get("id") or "")
                    break
        step("11_children_nonempty", bool(child_run_id), json.dumps(children, ensure_ascii=False)[:300], {"children": children})
        checklist["child_run_id"] = child_run_id

        # 5. 子挂起(kb:read 缺)→ 父节点 waiting_child + 父仍 running
        parent_status = ""
        node_status = ""
        child_status = ""
        for _ in range(40):
            time.sleep(0.5)
            r = client.get(f"/api/runs/{run_id}", headers=hm)
            if r.status_code == 200:
                parent_status = str(r.json().get("status") or "")
            rn = client.get(f"/api/runs/{run_id}/nodes", headers=hm)
            if rn.status_code == 200:
                nodes = rn.json().get("items") or []
                node_status = str((nodes[0] or {}).get("status") or "") if nodes else ""
            rc = client.get(f"/api/runs/{child_run_id}", headers=hm)
            if rc.status_code == 200:
                child_status = str(rc.json().get("status") or "")
            if parent_status == "running" and node_status == "waiting_child" and child_status == "suspended":
                break
        step(
            "12_waiting_child",
            parent_status == "running" and node_status == "waiting_child" and child_status == "suspended",
            f"parent={parent_status} node={node_status} child={child_status}",
            {"parent_status": parent_status, "node_status": node_status, "child_status": child_status},
        )

        # 9. admin 审批子 run 的挂起请求 → 子完成 → 父唤醒 → 父 succeeded
        req_id = ""
        reqs: list = []
        r = client.get("/api/workflow-approvals/inbox", headers=ha)
        if r.status_code == 200:
            _ib = r.json()
            reqs = _ib.get("items") if isinstance(_ib, dict) else (_ib if isinstance(_ib, list) else [])
            for req in reqs:
                if isinstance(req, dict) and req.get("run_id") == child_run_id:
                    req_id = str(req.get("id") or "")
                    break
        step("13_find_child_request", bool(req_id), json.dumps(reqs, ensure_ascii=False)[:400], {"request_id": req_id})
        if req_id:
            r = client.post(f"/api/workflow-approvals/{req_id}/approve", headers=ha, json={})
            step("14_approve_child_request", r.status_code == 200, r.text[:200])
        parent_final = ""
        child_final = ""
        for _ in range(60):
            time.sleep(0.5)
            rc = client.get(f"/api/runs/{child_run_id}", headers=hm)
            if rc.status_code == 200:
                child_final = str(rc.json().get("status") or "")
            rp = client.get(f"/api/runs/{run_id}", headers=hm)
            if rp.status_code == 200:
                parent_final = str(rp.json().get("status") or "")
            if parent_final == "succeeded" and child_final == "succeeded":
                break
        step(
            "15_parent_completes_after_child",
            parent_final == "succeeded" and child_final == "succeeded",
            f"parent={parent_final} child={child_final}",
            {"parent_status": parent_final, "child_status": child_final},
        )

        # 9b. Chat 桥:高置信触发句(function 1.0)→ workflow_triggered(不走 LLM 长答)
        # 注:教育句「帮我生成一份教育热点口播稿」当前分类器仅 conversation 0.6 < 0.7
        # (真实产品缺口:教育意图规则待补,education doc 已记录;桥逻辑由单测覆盖)
        # 触发句带唯一后缀:避免 exact cache 命中上一轮回复(cache_hit 短路,桥不跑)
        bridge_msg = f"提醒我明天下午三点开会,帮我记一下 {suffix}"
        r = client.post(
            "/chat",
            headers=hm,
            json={"message": bridge_msg, "session_id": f"g8-{suffix}", "user_id": member_user},
        )
        bridge = r.json() if r.status_code == 200 else {}
        finish = str(bridge.get("finish_reason") or "")
        resp = str(bridge.get("response") or "")
        step(
            "16_chat_bridge",
            finish == "workflow_triggered" and "正在生成" in resp,
            f"finish_reason={finish} response={resp[:120]}",
            {"trigger_message": bridge_msg, **bridge},
        )

        checklist["finished_at"] = datetime.now(timezone.utc).isoformat()
        checklist["passed"] = failed == 0
        summary_path = EVIDENCE / "00_summary.json"
        summary_path.write_text(
            json.dumps(checklist, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(f"summary → {summary_path}")
        print("RESULT:", "ALL_PASS" if failed == 0 else f"{failed} FAILED")
        sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
