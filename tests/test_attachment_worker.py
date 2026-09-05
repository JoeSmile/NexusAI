"""Task 76.2 — async parse worker: shared uploads volume, timeout, retries."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from packages.attachments.worker import (
    PARSE_TIMEOUT_SECONDS,
    ParseJob,
    run_parse_job,
)


def test_missing_uploads_volume_does_not_parse(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "not-mounted"))
    called = {"n": 0}

    def parse(_job: ParseJob):
        called["n"] += 1
        raise AssertionError("parser must not run without uploads volume")

    job = ParseJob(
        attachment_id="a1",
        tenant_id="t1",
        session_id="s1",
        filename="a.txt",
        storage_path=str(tmp_path / "not-mounted" / "a1"),
        attempts=0,
    )
    result = run_parse_job(job, parse_fn=parse)
    assert called["n"] == 0
    assert result.status == "failed"
    assert result.reason == "uploads_volume_missing"
    assert result.should_retry is False


def test_parse_timeout_marks_failed_and_retryable(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    path = uploads / "slow.bin"
    path.write_bytes(b"hello")
    monkeypatch.setenv("UPLOADS_DIR", str(uploads))

    def hang(_job: ParseJob):
        time.sleep(5)
        return []

    job = ParseJob(
        attachment_id="a2",
        tenant_id="t1",
        session_id="s1",
        filename="slow.txt",
        storage_path=str(path),
        attempts=0,
    )
    t0 = time.perf_counter()
    result = run_parse_job(job, parse_fn=hang, timeout_s=0.05)
    assert time.perf_counter() - t0 < 1.0
    assert result.status == "failed"
    assert result.reason == "parse_timeout"
    assert result.should_retry is True
    assert result.attempts == 1


def test_stops_retrying_after_two_retries(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    path = uploads / "x.txt"
    path.write_bytes(b"x")
    monkeypatch.setenv("UPLOADS_DIR", str(uploads))

    def boom(_job: ParseJob):
        raise RuntimeError("parse boom")

    job = ParseJob(
        attachment_id="a3",
        tenant_id="t1",
        session_id="s1",
        filename="x.txt",
        storage_path=str(path),
        attempts=2,
    )
    result = run_parse_job(job, parse_fn=boom)
    assert result.status == "failed"
    assert result.should_retry is False
    assert result.attempts == 3


def test_successful_parse_under_uploads_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    path = uploads / "note.txt"
    path.write_bytes(b"hello contract\n")
    monkeypatch.setenv("UPLOADS_DIR", str(uploads))
    job = ParseJob(
        attachment_id="a4",
        tenant_id="t1",
        session_id="s1",
        filename="note.txt",
        storage_path=str(path),
        attempts=0,
    )
    result = run_parse_job(job)
    assert result.status == "ready"
    assert result.blocks
    assert "hello" in result.blocks[0].text


def test_prod_compose_file_worker_shares_uploads_volume() -> None:
    text = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "file-worker:" in text
    assert "apps.file_worker" in text
    fw = text.split("file-worker:")[1].split("knowledge-worker:")[0]
    assert "./uploads:/app/uploads" in fw
    assert "knowledge-worker:" in text
    assert "apps.knowledge_worker" in text
    kw = text.split("knowledge-worker:")[1].split("social-worker:")[0]
    assert "./uploads:/app/uploads" in kw
    mem = text.split("memory-worker:")[1].split("file-worker:")[0]
    assert "./uploads:/app/uploads" not in mem


def test_parse_timeout_constant_is_60s() -> None:
    assert PARSE_TIMEOUT_SECONDS == 60
