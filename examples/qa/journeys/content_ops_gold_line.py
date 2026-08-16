#!/usr/bin/env python3
"""Task 45 金线 9' — 风格(可选) → 热点 → 口播 → artifacts.

Usage:
  Terminal 1: APP_ENV=dev LLM_PROVIDER=mock make run  (or uv run uvicorn…)
  Terminal 2: uv run python examples/qa/journeys/content_ops_gold_line.py

Env:
  SMOKE_BASE_URL  default http://127.0.0.1:8000
  SMOKE_API_KEY   optional X-API-Key (else register+login JWT)
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT", "120"))
EVIDENCE = Path(__file__).resolve().parent / "evidence" / "content_ops"
PASSWORD = "password123"


def _write(step: str, payload: object) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"{step}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def wait_health(client: httpx.Client) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if client.get("/health").status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise SystemExit("health timeout")


def auth_headers(client: httpx.Client) -> dict[str, str]:
    key = (os.getenv("SMOKE_API_KEY") or "").strip()
    if key:
        return {"X-API-Key": key}
    username = f"content_ops_{uuid.uuid4().hex[:10]}"
    r = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "display_name": "ContentOps",
            "role": "tenant_admin",
        },
    )
    _write("01_register", {"status": r.status_code, "body": r.text[:800]})
    if r.status_code == 200:
        token = str(r.json().get("access_token") or "")
        if token:
            return {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/api/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    _write("02_login", {"status": r.status_code, "body": r.text[:800]})
    r.raise_for_status()
    token = str(r.json().get("access_token") or "")
    if not token:
        raise SystemExit(f"no access_token: {r.text[:400]}")
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=TIMEOUT, trust_env=False) as client:
        wait_health(client)
        headers = auth_headers(client)

        r = client.get("/api/offerings?dept=content_growth", headers=headers)
        _write("03_offerings", {"status": r.status_code, "json": r.json() if r.status_code == 200 else r.text})
        assert r.status_code == 200, r.text
        ids = {i["id"] for i in r.json().get("items", [])}
        assert "wf.hotspot_dig" in ids and "wf.script_gen" in ids
        print("PASS  offerings")

        r = client.put(
            "/api/content/org-profile",
            headers=headers,
            json={
                "name": "星河教育",
                "industry": "教育培训",
                "product_focus": "少儿口才",
                "target_audience": "小学生家长",
            },
        )
        _write("04_org_profile", {"status": r.status_code, "json": r.json() if r.status_code == 200 else r.text})
        assert r.status_code == 200, r.text
        print("PASS  org profile")

        speech = (
            "同学们好，咱们今天就一件事：把习惯养成说清楚。"
            "你品，你细品，先痛点再方法。"
            "不承诺提分，我们只讲能落地的小动作。"
        )
        r = client.post(
            "/api/content/styles/default/extract",
            headers=headers,
            json={"text": speech, "save": True},
        )
        _write("05_style_extract", {"status": r.status_code, "json": r.json() if r.status_code == 200 else r.text})
        assert r.status_code == 200, r.text
        print("PASS  style extract")

        r = client.post(
            "/api/content/hotspots/dig",
            headers=headers,
            json={"adapter": "topic_agent", "keywords": "习惯", "save": True},
        )
        _write("06_hotspot", {"status": r.status_code, "json": r.json() if r.status_code == 200 else r.text})
        assert r.status_code == 200, r.text
        hot = r.json()
        assert hot.get("count", 0) >= 1
        print("PASS  hotspot dig")

        r = client.post(
            "/api/content/scripts/generate",
            headers=headers,
            json={
                "creator_id": "default",
                "hotspots": hot.get("items") or [],
                "duration_sec": 60,
                "student_names": ["李明"],
                "save": True,
            },
        )
        _write("07_script", {"status": r.status_code, "json": r.json() if r.status_code == 200 else r.text})
        assert r.status_code == 200, r.text
        script = r.json().get("script") or ""
        assert len(script) > 10
        print("PASS  script gen")

        r = client.get("/api/content/artifacts", headers=headers)
        _write("08_artifacts", {"status": r.status_code, "json": r.json() if r.status_code == 200 else r.text})
        assert r.status_code == 200, r.text
        assert r.json().get("count", 0) >= 1
        print("PASS  artifacts")

        # no-style path: wipe style by using unknown creator — still succeeds
        r = client.post(
            "/api/content/scripts/generate",
            headers=headers,
            json={"creator_id": "never_configured_xyz", "hotspots": [], "save": False},
        )
        _write("09_default_style", {"status": r.status_code, "json": r.json() if r.status_code == 200 else r.text})
        assert r.status_code == 200, r.text
        assert r.json().get("style_is_default") is True or len(r.json().get("script") or "") > 0
        print("PASS  default style no error")

    print("ALL PASS — evidence in", EVIDENCE)


if __name__ == "__main__":
    main()
