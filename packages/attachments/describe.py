"""image.describe — tenant vision BYOK, OCR/explicit error, Redis TTL 7d."""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from packages.attachments.notice import row_is_live
from packages.attachments.store import AttachmentForbidden, get_attachment_store
from packages.audit import write_audit_sync
from packages.errors import NexusAIException
from packages.harness import LLMHarness
from packages.multimodal.vision import (
    build_vision_messages,
    image_to_data_uri,
    resolve_vision_credentials,
    select_vision_model_name,
)
from packages.redis_tools import cache_key, get_sync_redis

logger = logging.getLogger(__name__)

LONG_EDGE_MAX = 1568
DESCRIBE_CACHE_TTL = 7 * 24 * 3600
AUDIT_SUMMARY_CHARS = 160
DEFAULT_PROMPT = (
    "请描述这张图片。"
    "若是界面截图，列出界面元素、按钮，并逐字转写可见报错与文案；"
    "若是图表，说明坐标、趋势与异常点，结论放最后；"
    "若是文档照片，说明版式并转写文字。"
)

_harness = LLMHarness()


class DescribeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def describe_cache_key(tenant_id: str, attachment_id: str) -> str:
    return cache_key("img", "desc", tenant_id, attachment_id)


def compress_image_bytes(
    data: bytes, *, content_type: str = "image/png"
) -> tuple[bytes, str]:
    try:
        src = Image.open(io.BytesIO(data))
        src.load()
    except Image.DecompressionBombError as exc:
        raise DescribeError("FILE_TOO_LARGE", "image_too_many_pixels") from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise DescribeError("FILE_PARSE", "image_unreadable") from exc
    img = src
    try:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        width, height = img.size
        long_edge = max(width, height)
        if long_edge > LONG_EDGE_MAX:
            scale = LONG_EDGE_MAX / float(long_edge)
            img = img.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )
        buf = io.BytesIO()
        jpeg = "jpeg" in (content_type or "") or "jpg" in (content_type or "")
        if jpeg:
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=85, optimize=True)
            return buf.getvalue(), "image/jpeg"
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png"
    finally:
        try:
            src.close()
        except Exception:
            pass
        if img is not src:
            try:
                img.close()
            except Exception:
                pass


def ocr_image_path(path: str) -> str:
    try:
        from packages.rag.extractors.image import extract_image_text

        return (extract_image_text(path) or "").strip()
    except Exception:
        logger.debug("image ocr unavailable", exc_info=True)
        return ""


async def tenant_has_vision(tenant_id: str) -> bool:
    """True only when this tenant has a vision BYOK row — no platform key fallback."""
    try:
        name = select_vision_model_name()
    except NexusAIException:
        return False
    try:
        from packages.llm_credentials import resolve_tenant_credential

        await resolve_tenant_credential(tenant_id, name)
        return True
    except Exception:
        return False


def _ttl_seconds(row: dict[str, Any]) -> int:
    exp = row.get("expired_at")
    if exp is None:
        return DESCRIBE_CACHE_TTL
    if getattr(exp, "tzinfo", None) is None:
        exp = exp.replace(tzinfo=UTC)
    left = int((exp - datetime.now(UTC)).total_seconds())
    return max(60, min(left, DESCRIBE_CACHE_TTL))


def _audit(
    *,
    tenant_id: str,
    user_id: str,
    attachment_id: str,
    action: str,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    summary: str = "",
    error_code: str | None = None,
) -> None:
    try:
        write_audit_sync(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "action": action,
                "trace_id": "",
                "input_text": attachment_id[:64],
                "output_text": (summary or "")[:AUDIT_SUMMARY_CHARS],
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "error_code": error_code,
            }
        )
    except Exception:
        logger.debug("image.describe audit skipped", exc_info=True)


def _cache_get(tenant_id: str, attachment_id: str) -> dict[str, Any] | None:
    try:
        client = get_sync_redis(decode_responses=True)
    except Exception:
        return None
    if client is None:
        return None
    key = describe_cache_key(tenant_id, attachment_id)
    try:
        raw = client.get(key)
    except Exception:
        logger.debug("image.describe cache get failed", exc_info=True)
        return None
    if not raw:
        return None
    try:
        row = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict) or not row.get("text"):
        return None
    return row


def _cache_set(tenant_id: str, attachment_id: str, payload: dict[str, Any], ttl: int) -> None:
    try:
        client = get_sync_redis(decode_responses=True)
    except Exception:
        return
    if client is None:
        return
    key = describe_cache_key(tenant_id, attachment_id)
    try:
        client.set(key, json.dumps(payload, ensure_ascii=False), ex=ttl)
    except Exception:
        logger.debug("image.describe cache set failed", exc_info=True)


def _is_image(row: dict[str, Any]) -> bool:
    media = str(row.get("media_type") or "")
    name = str(row.get("name") or "").lower()
    return media.startswith("image/") or name.rsplit(".", 1)[-1] in {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
    }


async def describe_image(
    *,
    tenant_id: str,
    user_id: str,
    session_id: str,
    attachment_id: str,
    query_hint: str | None = None,
) -> dict[str, Any]:
    store = get_attachment_store()
    try:
        row = store.get(
            tenant_id=tenant_id,
            session_id=session_id,
            attachment_id=attachment_id,
        )
    except AttachmentForbidden as exc:
        _audit(
            tenant_id=tenant_id,
            user_id=user_id,
            attachment_id=attachment_id,
            action="attachment_denied",
            error_code="AUTH_004",
            summary=exc.reason,
        )
        raise DescribeError("AUTH_004", exc.reason) from exc

    if row is None:
        raise DescribeError("FILE_NOT_FOUND", "attachment_not_found")
    if not row_is_live(row):
        raise DescribeError("FILE_NOT_FOUND", "attachment_expired")
    if not _is_image(row):
        raise DescribeError("FILE_TYPE", "not_an_image")

    cached = _cache_get(tenant_id, attachment_id)
    if cached:
        return {
            "text": str(cached["text"]),
            "source": str(cached.get("source") or "vision"),
            "model": str(cached.get("model") or ""),
            "tokens": int(cached.get("tokens") or 0),
            "cached": True,
        }

    path = str(row.get("storage_path") or "")
    try:
        data = Path(path).read_bytes() if path else b""
    except OSError as exc:
        raise DescribeError("FILE_NOT_FOUND", "image_unreadable") from exc
    if not data:
        raise DescribeError("FILE_EMPTY", "empty_image")

    prompt = (query_hint or "").strip() or DEFAULT_PROMPT
    media = str(row.get("media_type") or "image/png")
    text = ""
    source = "vision"
    model = ""
    in_tok = 0
    out_tok = 0

    if await tenant_has_vision(tenant_id):
        compressed, ctype = compress_image_bytes(data, content_type=media)
        try:
            model, api_key, base_url, provider = await resolve_vision_credentials(
                tenant_id
            )
            uri = image_to_data_uri(compressed, ctype)
            messages = build_vision_messages(prompt, uri)
            result = await _harness.generate(
                model=model,
                messages=messages,
                tenant_id=tenant_id,
                api_key=api_key,
                base_url=base_url,
                provider=provider,
                max_tokens=1024,
            )
        except Exception:
            logger.debug("image.describe vision call failed", exc_info=True)
            result = None
        if result is not None and result.success:
            text = str(result.output or "").strip()
            in_tok = int((result.metadata or {}).get("input_tokens", 0) or 0)
            out_tok = int((result.metadata or {}).get("output_tokens", 0) or 0)
        if not text:
            ocr = ocr_image_path(path)
            if ocr:
                text, source, model = ocr, "ocr", model or "ocr"
            else:
                _audit(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    attachment_id=attachment_id,
                    action="image.describe",
                    model=model,
                    error_code="VISION_UNAVAILABLE",
                )
                raise DescribeError("VISION_UNAVAILABLE", "vision_describe_failed")
    else:
        source = "ocr"
        text = ocr_image_path(path)
        if not text:
            _audit(
                tenant_id=tenant_id,
                user_id=user_id,
                attachment_id=attachment_id,
                action="image.describe",
                error_code="VISION_UNAVAILABLE",
            )
            raise DescribeError("VISION_UNAVAILABLE", "vision_not_configured")

    payload = {
        "text": text,
        "source": source,
        "model": model,
        "tokens": in_tok + out_tok,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }
    _cache_set(tenant_id, attachment_id, payload, _ttl_seconds(row))
    _audit(
        tenant_id=tenant_id,
        user_id=user_id,
        attachment_id=attachment_id,
        action="image.describe",
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        summary=text,
    )
    return {
        "text": text,
        "source": source,
        "model": model,
        "tokens": in_tok + out_tok,
        "cached": False,
    }
