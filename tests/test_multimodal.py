"""Task 58 — multimodal vision upload + governance."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from packages.auth.dual_auth import verify_human_or_legacy_key
from backend.core.guardrails.image_guard import check_image_input, image_content_hash
from backend.core.harness.base import HarnessResult
from backend.core.model_registry import get_model, list_vision_models, reload_registry
from backend.core.multimodal.vision import build_vision_messages
from backend.routers.multimodal import router as multimodal_router


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(120, 80, 200)).save(buf, format="PNG")
    return buf.getvalue()


def test_vision_model_in_registry() -> None:
    reload_registry()
    models = list_vision_models()
    assert any(m.name == "qwen-vl-plus" for m in models)
    spec = get_model("qwen-vl-plus")
    assert spec is not None
    assert spec.capability == "vision"


def test_image_guard_hash() -> None:
    data = _png_bytes()
    ok, code, digest = check_image_input(
        content=data, filename="x.png", content_type="image/png"
    )
    assert ok is True
    assert code == ""
    assert digest == image_content_hash(data)


def test_build_vision_messages() -> None:
    uri = "data:image/png;base64,abc"
    msgs = build_vision_messages("图里有什么", uri)
    assert msgs[0]["role"] == "user"
    content = msgs[0]["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "image_url"


def test_multimodal_chat_mock_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.auth.models import TenantContext
    from backend.routers import multimodal as mm_mod

    reload_registry()
    monkeypatch.setattr(
        mm_mod,
        "resolve_vision_credentials",
        AsyncMock(return_value=("qwen-vl-plus", "k", "http://x", "qwen")),
    )
    monkeypatch.setattr(
        mm_mod,
        "enforce_terms_for_chat",
        lambda **_k: None,
    )
    monkeypatch.setattr(
        mm_mod._harness,
        "generate",
        AsyncMock(
            return_value=HarnessResult(
                output="mock vision reply",
                type="llm",
                name="qwen-vl-plus",
                success=True,
                metadata={"input_tokens": 100, "output_tokens": 20, "cost": 0.01},
            )
        ),
    )

    tenant = TenantContext("acme", "u1", "tenant_admin", [], False)

    app = FastAPI()
    app.include_router(multimodal_router, prefix="/api")

    async def _auth() -> TenantContext:
        return tenant

    app.dependency_overrides[verify_human_or_legacy_key] = _auth

    client = TestClient(app)
    r = client.post(
        "/api/multimodal/chat",
        data={"text": "这张图里有什么"},
        files={"file": ("demo.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert "mock vision" in body["response"]
    assert body["context"]["modality"] == "image"
    assert body["context"]["image_hash"]


def test_multimodal_denied_without_permission() -> None:
    from packages.auth.models import TenantContext

    user = TenantContext("acme", "u1", "user", [], False)
    app = FastAPI()
    app.include_router(multimodal_router, prefix="/api")

    async def _auth() -> TenantContext:
        return user

    app.dependency_overrides[verify_human_or_legacy_key] = _auth
    r = TestClient(app).post(
        "/api/multimodal/chat",
        data={"text": "hi"},
        files={"file": ("demo.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 403
