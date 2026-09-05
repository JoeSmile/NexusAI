"""Task 71 slice 2 — chat error messages must not leak internals."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "packages" / "pipeline"
_SAFE_SSE = "生成失败，请稍后重试或换个说法。"
_MSG_STR_RE = re.compile(r'''["']message["']\s*:\s*str\(''')


def test_streaming_error_uses_safe_copy() -> None:
    src = (PIPELINE / "router.py").read_text(encoding="utf-8")
    assert _SAFE_SSE in src


def test_pipeline_has_no_message_str_e_leak() -> None:
    """Chat pipeline surface: no `"message": str(...)` (Task 71)."""
    leaks: list[str] = []
    for path in PIPELINE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if _MSG_STR_RE.search(line):
                leaks.append(f"{path.relative_to(ROOT)}:{i}:{line.strip()}")
    assert leaks == [], "pipeline error payloads must not use str(e):\n" + "\n".join(leaks)
