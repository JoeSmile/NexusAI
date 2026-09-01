"""Task 76.4 — image.describe: vision BYOK, OCR/error, 7d cache, audit, not RAG."""

from __future__ import annotations

import inspect
import io
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from packages.attachments.store import MemoryAttachmentStore, set_attachment_store
from packages.auth.models import TenantContext


@pytest.fixture(autouse=True)
def _quiet_describe_audit(monkeypatch: pytest.MonkeyPatch):
    try:
        from packages.attachments import describe as desc
    except ImportError:
        return
    monkeypatch.setattr(desc, "write_audit_sync", lambda rec: True, raising=False)


def _png_bytes(w: int = 8, h: int = 8) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color=(40, 90, 180)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def image_row(tmp_path):
    store = MemoryAttachmentStore()
    set_attachment_store(store)
    data = _png_bytes()
    path = tmp_path / "shot.png"
    path.write_bytes(data)
    aid = store.save(
        tenant_id="t1",
        session_id="s1",
        uploaded_by="u1",
        name="shot.png",
        media_type="image/png",
        size=len(data),
        status="ready",
        storage_path=str(path),
        expired_at=datetime.now(UTC) + timedelta(days=7),
        blocks=[],
        attachment_id="attimg01" + "ab" * 12,
    )
    yield {"store": store, "aid": aid, "path": path, "data": data}
    set_attachment_store(None)


class _FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.set_calls.append((key, value, ex))
        self.kv[key] = value
        return True


def test_png_magic_is_valid_session_attachment() -> None:
    from packages.attachments.validate import validate_attachment_bytes

    kind = validate_attachment_bytes(filename="shot.png", data=_png_bytes())
    assert kind == "image"


def test_parse_image_ready_without_text_blocks() -> None:
    from packages.attachments.parse import parse_document

    out = parse_document(_png_bytes(), "shot.png")
    assert out.status == "ready"
    assert out.media_type.startswith("image/")
    assert out.blocks == []


def test_compress_long_edge_at_most_1568() -> None:
    from packages.attachments.describe import LONG_EDGE_MAX, compress_image_bytes

    raw = _png_bytes(2000, 1000)
    out, ctype = compress_image_bytes(raw, content_type="image/png")
    img = Image.open(io.BytesIO(out))
    assert max(img.size) <= LONG_EDGE_MAX
    assert max(img.size) == LONG_EDGE_MAX
    assert ctype.startswith("image/")


@pytest.mark.asyncio
async def test_vision_describe_returns_text_not_knowledge(
    image_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc
    from packages.harness.base import HarnessResult

    fake = _FakeRedis()
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(desc, "tenant_has_vision", AsyncMock(return_value=True))
    monkeypatch.setattr(
        desc,
        "resolve_vision_credentials",
        AsyncMock(return_value=("qwen-vl-plus", "k", "http://x", "qwen")),
    )

    class _H:
        async def generate(self, **_k):
            return HarnessResult(
                output="图表横轴是月份，销量上升。",
                success=True,
                metadata={"input_tokens": 80, "output_tokens": 20},
            )

    monkeypatch.setattr(desc, "_harness", _H())

    result = await desc.describe_image(
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        attachment_id=image_row["aid"],
    )
    assert result["source"] == "vision"
    assert "销量" in result["text"]
    src = inspect.getsource(desc)
    assert "knowledge_chunks" not in src
    assert "add_documents" not in src


@pytest.mark.asyncio
async def test_no_vision_uses_ocr_fallback(
    image_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc

    fake = _FakeRedis()
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(desc, "tenant_has_vision", AsyncMock(return_value=False))
    monkeypatch.setattr(desc, "ocr_image_path", lambda _p: "截图文字：提交失败")

    result = await desc.describe_image(
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        attachment_id=image_row["aid"],
    )
    assert result["source"] == "ocr"
    assert "提交失败" in result["text"]


@pytest.mark.asyncio
async def test_no_vision_no_ocr_raises_explicit(
    image_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc
    from packages.attachments.describe import DescribeError

    fake = _FakeRedis()
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(desc, "tenant_has_vision", AsyncMock(return_value=False))
    monkeypatch.setattr(desc, "ocr_image_path", lambda _p: "")

    with pytest.raises(DescribeError) as ei:
        await desc.describe_image(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            attachment_id=image_row["aid"],
        )
    assert ei.value.code == "VISION_UNAVAILABLE"
    assert ei.value.message


@pytest.mark.asyncio
async def test_describe_redis_cache_ttl_matches_attachment(
    image_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc
    from packages.harness.base import HarnessResult

    fake = _FakeRedis()
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(desc, "tenant_has_vision", AsyncMock(return_value=True))
    monkeypatch.setattr(
        desc,
        "resolve_vision_credentials",
        AsyncMock(return_value=("qwen-vl-plus", "k", "http://x", "qwen")),
    )

    class _H:
        async def generate(self, **_k):
            return HarnessResult(
                output="cached caption",
                success=True,
                metadata={"input_tokens": 10, "output_tokens": 4},
            )

    monkeypatch.setattr(desc, "_harness", _H())

    first = await desc.describe_image(
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        attachment_id=image_row["aid"],
    )
    assert first.get("cached") is not True
    assert fake.set_calls
    _key, _val, ex = fake.set_calls[0]
    assert ex is not None
    assert 7 * 24 * 3600 - 120 <= int(ex) <= 7 * 24 * 3600
    digest = desc.content_digest(image_row["data"])
    assert _key == desc.describe_cache_key("t1", digest)

    second = await desc.describe_image(
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        attachment_id=image_row["aid"],
    )
    assert second["cached"] is True
    assert second["text"] == "cached caption"


@pytest.mark.asyncio
async def test_cross_tenant_denied_and_audited(
    image_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc
    from packages.attachments.describe import DescribeError

    audits: list[dict] = []
    monkeypatch.setattr(desc, "write_audit_sync", lambda rec: audits.append(rec) or True)
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: None)

    with pytest.raises(DescribeError) as ei:
        await desc.describe_image(
            tenant_id="t-other",
            user_id="u1",
            session_id="s1",
            attachment_id=image_row["aid"],
        )
    assert ei.value.code in {"AUTH_004", "ATTACHMENT_DENIED"}
    assert any(
        a.get("action") in {"image.describe", "attachment_denied"} for a in audits
    )


@pytest.mark.asyncio
async def test_audit_summary_not_full_body(
    image_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc
    from packages.harness.base import HarnessResult

    audits: list[dict] = []
    fake = _FakeRedis()
    monkeypatch.setattr(desc, "write_audit_sync", lambda rec: audits.append(rec) or True)
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(desc, "tenant_has_vision", AsyncMock(return_value=True))
    monkeypatch.setattr(
        desc,
        "resolve_vision_credentials",
        AsyncMock(return_value=("qwen-vl-plus", "k", "http://x", "qwen")),
    )
    long_body = "结论。" + ("细节" * 400)

    class _H:
        async def generate(self, **_k):
            return HarnessResult(
                output=long_body,
                success=True,
                metadata={"input_tokens": 100, "output_tokens": 50},
            )

    monkeypatch.setattr(desc, "_harness", _H())

    await desc.describe_image(
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        attachment_id=image_row["aid"],
    )
    assert audits
    rec = audits[-1]
    assert rec["action"] == "image.describe"
    assert image_row["aid"] in str(rec.get("input_text") or "")
    assert rec.get("model") == "qwen-vl-plus"
    tokens = int(rec.get("input_tokens") or 0) + int(rec.get("output_tokens") or 0)
    assert tokens == 150
    out = str(rec.get("output_text") or "")
    assert long_body not in out
    assert len(out) <= 200


@pytest.mark.asyncio
async def test_expired_attachment_refused(
    image_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc
    from packages.attachments.describe import DescribeError

    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: None)
    image_row["store"].items[image_row["aid"]]["expired_at"] = datetime.now(UTC) - timedelta(
        hours=1
    )
    with pytest.raises(DescribeError) as ei:
        await desc.describe_image(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            attachment_id=image_row["aid"],
        )
    assert ei.value.code == "FILE_NOT_FOUND"


def test_image_describe_builtin_spec() -> None:
    from packages.capability.builtin.specs import BUILTIN_TOOL_SPECS

    ids = {str(raw["id"]) for raw in BUILTIN_TOOL_SPECS}
    assert "image.describe" in ids


@pytest.mark.asyncio
async def test_builtin_handler_describe(
    image_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc
    from packages.capability.builtin.handlers import invoke_builtin_handler
    from packages.harness.base import HarnessResult

    fake = _FakeRedis()
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(desc, "tenant_has_vision", AsyncMock(return_value=True))
    monkeypatch.setattr(
        desc,
        "resolve_vision_credentials",
        AsyncMock(return_value=("qwen-vl-plus", "k", "http://x", "qwen")),
    )

    class _H:
        async def generate(self, **_k):
            return HarnessResult(output="ok-img", success=True, metadata={})

    monkeypatch.setattr(desc, "_harness", _H())

    tenant = TenantContext("t1", "u1", "user", ["chat:write"], False)
    result = await invoke_builtin_handler(
        "image.describe",
        {"attachment_id": image_row["aid"], "session_id": "s1"},
        tenant,
    )
    assert result.get("ok") is True
    payload = result.get("data") or result
    assert "ok-img" in str(payload.get("text") or payload)


def test_upload_png_session_attachment(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from apps.api.routers.files import router as files_router
    from packages.auth.dual_auth import verify_human_or_legacy_key

    store = MemoryAttachmentStore()
    set_attachment_store(store)
    import apps.api.routers.files as files_mod

    monkeypatch.setattr(files_mod, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(files_mod, "write_audit_sync", lambda rec: True)

    app = FastAPI()
    app.include_router(files_router)
    app.dependency_overrides[verify_human_or_legacy_key] = lambda: TenantContext(
        "t1", "u1", "user", [], False
    )
    client = TestClient(app)
    r = client.post(
        "/api/files",
        files={"file": ("shot.png", _png_bytes(), "image/png")},
        data={"session_id": "s1"},
    )
    set_attachment_store(None)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["blocks"] == []
    assert body["attachment_id"]


def test_describe_cache_key_uses_content_digest_not_attachment_id() -> None:
    from packages.attachments.describe import content_digest, describe_cache_key

    digest = content_digest(_png_bytes())
    assert len(digest) == 16
    key = describe_cache_key("t1", digest)
    assert key.startswith("img:desc:t1:")
    assert "attimg" not in key
    assert digest in key


@pytest.mark.asyncio
async def test_same_bytes_second_attachment_hits_hash_cache(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc
    from packages.harness.base import HarnessResult

    store = MemoryAttachmentStore()
    set_attachment_store(store)
    data = _png_bytes()
    calls = {"n": 0}

    def _save(tid: str, sid: str, aid: str) -> str:
        path = tmp_path / f"{aid}.png"
        path.write_bytes(data)
        return store.save(
            tenant_id=tid,
            session_id=sid,
            uploaded_by="u1",
            name="shot.png",
            media_type="image/png",
            size=len(data),
            status="ready",
            storage_path=str(path),
            expired_at=datetime.now(UTC) + timedelta(days=7),
            blocks=[],
            attachment_id=aid,
        )

    aid1 = _save("t1", "s1", "a" * 32)
    aid2 = _save("t1", "s1", "b" * 32)
    fake = _FakeRedis()
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(desc, "tenant_has_vision", AsyncMock(return_value=True))
    monkeypatch.setattr(
        desc,
        "resolve_vision_credentials",
        AsyncMock(return_value=("qwen-vl-plus", "k", "http://x", "qwen")),
    )

    class _H:
        async def generate(self, **_k):
            calls["n"] += 1
            return HarnessResult(output="same-bytes-caption", success=True, metadata={})

    monkeypatch.setattr(desc, "_harness", _H())
    first = await desc.describe_image(
        tenant_id="t1", user_id="u1", session_id="s1", attachment_id=aid1
    )
    second = await desc.describe_image(
        tenant_id="t1", user_id="u1", session_id="s1", attachment_id=aid2
    )
    set_attachment_store(None)
    assert first["text"] == "same-bytes-caption"
    assert second["cached"] is True
    assert second["text"] == "same-bytes-caption"
    assert calls["n"] == 1
    assert fake.set_calls
    digest = desc.content_digest(data)
    assert desc.describe_cache_key("t1", digest) == fake.set_calls[0][0]


@pytest.mark.asyncio
async def test_same_bytes_other_tenant_does_not_share_cache(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.attachments import describe as desc
    from packages.harness.base import HarnessResult

    store = MemoryAttachmentStore()
    set_attachment_store(store)
    data = _png_bytes()
    calls = {"n": 0}

    def _save(tid: str, aid: str) -> str:
        path = tmp_path / f"{aid}.png"
        path.write_bytes(data)
        return store.save(
            tenant_id=tid,
            session_id="s1",
            uploaded_by="u1",
            name="shot.png",
            media_type="image/png",
            size=len(data),
            status="ready",
            storage_path=str(path),
            expired_at=datetime.now(UTC) + timedelta(days=7),
            blocks=[],
            attachment_id=aid,
        )

    _save("t1", "a" * 32)
    _save("t2", "c" * 32)
    fake = _FakeRedis()
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(desc, "tenant_has_vision", AsyncMock(return_value=True))
    monkeypatch.setattr(
        desc,
        "resolve_vision_credentials",
        AsyncMock(return_value=("qwen-vl-plus", "k", "http://x", "qwen")),
    )

    class _H:
        async def generate(self, **_k):
            calls["n"] += 1
            return HarnessResult(output=f"cap-{calls['n']}", success=True, metadata={})

    monkeypatch.setattr(desc, "_harness", _H())
    await desc.describe_image(
        tenant_id="t1", user_id="u1", session_id="s1", attachment_id="a" * 32
    )
    other = await desc.describe_image(
        tenant_id="t2", user_id="u1", session_id="s1", attachment_id="c" * 32
    )
    set_attachment_store(None)
    assert calls["n"] == 2
    assert other.get("cached") is not True
    assert other["text"] == "cap-2"


@pytest.mark.asyncio
async def test_legacy_attachment_id_cache_key_still_read(
    image_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from packages.attachments import describe as desc
    from packages.harness.base import HarnessResult

    fake = _FakeRedis()
    old_key = desc.legacy_describe_cache_key("t1", image_row["aid"])
    fake.kv[old_key] = json.dumps({"text": "from-legacy", "source": "vision", "tokens": 1})
    monkeypatch.setattr(desc, "get_sync_redis", lambda **_k: fake)
    monkeypatch.setattr(desc, "tenant_has_vision", AsyncMock(return_value=True))

    class _H:
        async def generate(self, **_k):
            return HarnessResult(output="should-not-run", success=True, metadata={})

    monkeypatch.setattr(desc, "_harness", _H())
    result = await desc.describe_image(
        tenant_id="t1",
        user_id="u1",
        session_id="s1",
        attachment_id=image_row["aid"],
    )
    assert result["cached"] is True
    assert result["text"] == "from-legacy"
