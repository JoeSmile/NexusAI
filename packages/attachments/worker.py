"""Async parse job: volume gate, 60s timeout, retry ≤2."""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.attachments.parse import AttachmentBlock, ParseResult, parse_document

PARSE_TIMEOUT_SECONDS = 60
MAX_PARSE_ATTEMPTS = 3  # first try + 2 retries


@dataclass
class ParseJob:
    attachment_id: str
    tenant_id: str
    session_id: str
    filename: str
    storage_path: str
    attempts: int = 0


@dataclass
class ParseJobResult:
    status: str
    reason: str
    attempts: int
    should_retry: bool
    blocks: list[AttachmentBlock] = field(default_factory=list)


def uploads_root() -> Path:
    raw = (os.getenv("UPLOADS_DIR") or os.getenv("UPLOAD_DIR") or "./uploads").strip()
    return Path(raw).expanduser()


def path_visible_on_uploads_volume(storage_path: str) -> bool:
    root = uploads_root()
    try:
        root_res = root.resolve()
    except OSError:
        return False
    if not root_res.is_dir():
        return False
    try:
        dest = Path(storage_path).resolve()
        dest.relative_to(root_res)
    except (OSError, ValueError):
        return False
    return dest.is_file()


def _default_parse(job: ParseJob) -> ParseResult:
    data = Path(job.storage_path).read_bytes()
    return parse_document(data, job.filename)


def _fail(job: ParseJob, reason: str, *, retry: bool) -> ParseJobResult:
    nxt = job.attempts + 1
    if not retry:
        return ParseJobResult(
            status="failed",
            reason=reason,
            attempts=nxt,
            should_retry=False,
        )
    return ParseJobResult(
        status="failed",
        reason=reason,
        attempts=nxt,
        should_retry=nxt < MAX_PARSE_ATTEMPTS,
    )


def run_parse_job(
    job: ParseJob,
    *,
    parse_fn: Callable[[ParseJob], Any] | None = None,
    timeout_s: float | None = None,
) -> ParseJobResult:
    timeout = PARSE_TIMEOUT_SECONDS if timeout_s is None else timeout_s
    if not path_visible_on_uploads_volume(job.storage_path):
        return _fail(job, "uploads_volume_missing", retry=False)

    fn = parse_fn or _default_parse
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(fn, job)
        raw = fut.result(timeout=timeout)
    except FuturesTimeout:
        return _fail(job, "parse_timeout", retry=True)
    except Exception:
        return _fail(job, "parse_error", retry=True)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if isinstance(raw, ParseResult):
        return ParseJobResult(
            status=raw.status,
            reason="",
            attempts=job.attempts + 1,
            should_retry=False,
            blocks=list(raw.blocks),
        )
    return ParseJobResult(
        status="ready",
        reason="",
        attempts=job.attempts + 1,
        should_retry=False,
        blocks=[],
    )
