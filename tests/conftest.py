"""Test defaults: do not spam OTLP to local Langfuse during unit tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _quiet_langfuse_unless_requested():
    if os.getenv("LANGFUSE_IN_TESTS", "").strip() in {"1", "true", "yes"}:
        yield
        return
    prev = {k: os.environ.get(k) for k in (
        "LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
        "LANGFUSE_BASE_URL",
    )}
    os.environ["LANGFUSE_ENABLED"] = "0"
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    # Reset singleton if already warmed by import
    try:
        import backend.observability.langfuse_client as lf

        lf._lf = None
        lf._init_attempted = False
    except Exception:
        pass
    yield
    for k, v in prev.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
