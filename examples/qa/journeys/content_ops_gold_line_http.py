"""Content ops gold line 9' — HTTP against a running NexusAI.

Keeps the in-process seed journey (`content_ops_gold_line.py`) for CI.
This script proves the live stack: login → offerings → org-profile →
hotspot dig (adapter=seed) → script.gen → artifacts.

Usage:
    uv run python examples/qa/journeys/content_ops_gold_line_http.py

Env (optional):
    NEXUSAI_BASE_URL     default http://127.0.0.1:8000
    GOLD_LINE_USER       default admin_acme
    GOLD_LINE_PASSWORD   default 123456
"""

from __future__ import annotations

import os
import sys
from typing import Any

import requests

_ROOT_HINT = (
    "If login fails with AUTH_017, run alembic upgrade head "
    "and uv run python scripts/seed_api_keys.py"
)


def _base() -> str:
    return os.environ.get("NEXUSAI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _login(base: str) -> str:
    user = os.environ.get("GOLD_LINE_USER", "admin_acme")
    password = os.environ.get("GOLD_LINE_PASSWORD", "123456")
    r = requests.post(
        f"{base}/api/auth/login",
        json={"username": user, "password": password},
        timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"login HTTP {r.status_code}: {r.text[:400]} ({_ROOT_HINT})"
        )
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("login missing access_token")
    return str(token)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _raise_for(r: requests.Response, step: str) -> Any:
    if r.status_code >= 400:
        raise RuntimeError(f"{step} HTTP {r.status_code}: {r.text[:600]}")
    if not r.content:
        return {}
    return r.json()


def run_http_gold_line(*, base: str | None = None) -> dict[str, object]:
    root = base or _base()
    token = _login(root)
    h = _headers(token)

    offerings = _raise_for(
        requests.get(f"{root}/api/offerings", headers=h, timeout=15),
        "offerings",
    )
    ids = {i.get("id") for i in offerings.get("items") or []}
    if "wf.hotspot_dig" not in ids or "wf.script_gen" not in ids:
        raise RuntimeError(f"offerings missing implemented workflows: {ids}")

    _raise_for(
        requests.put(
            f"{root}/api/content/org-profile",
            headers=h,
            json={
                "name": "金线教培",
                "industry": "K12",
                "product_focus": "入学适应",
                "target_audience": "家长",
            },
            timeout=15,
        ),
        "org-profile",
    )

    dig = _raise_for(
        requests.post(
            f"{root}/api/content/hotspots/dig",
            headers=h,
            json={"adapter": "seed", "categories": ["K12"], "save": True},
            timeout=60,
        ),
        "hotspot.dig",
    )
    items = list(dig.get("items") or [])
    if not items:
        raise RuntimeError("hotspot.dig returned no items")

    gen = _raise_for(
        requests.post(
            f"{root}/api/content/scripts/generate",
            headers=h,
            json={
                "creator_id": "default",
                "hotspots": items[:2],
                "duration_sec": 60,
                "platform": "douyin",
                "student_names": ["李明"],
                "save": True,
            },
            timeout=120,
        ),
        "script.gen",
    )
    script = str(gen.get("script") or "")
    if not script.strip():
        raise RuntimeError("script.gen empty")
    if "李明" in script:
        raise RuntimeError("G7 failed: student name leaked in script")

    arts = _raise_for(
        requests.get(
            f"{root}/api/content/artifacts",
            headers=h,
            params={"kind": "script", "limit": 5},
            timeout=15,
        ),
        "artifacts",
    )
    if int(arts.get("count") or 0) < 1 and not gen.get("artifact_id"):
        raise RuntimeError("no script artifact after generate")

    return {
        "hotspot_count": dig.get("count") or len(items),
        "script_chars": len(script),
        "artifact_id": gen.get("artifact_id"),
        "offerings": ["wf.hotspot_dig", "wf.script_gen"],
    }


def main() -> int:
    try:
        result = run_http_gold_line()
    except requests.ConnectionError as exc:
        print(
            f"GOLD_LINE_HTTP_FAIL: cannot reach {_base()} ({exc})",
            file=sys.stderr,
        )
        return 2
    print("GOLD_LINE_HTTP_OK")
    print(
        f"hotspots={result['hotspot_count']} "
        f"script_chars={result['script_chars']} "
        f"artifact_id={result['artifact_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
