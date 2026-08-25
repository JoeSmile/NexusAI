#!/usr/bin/env python3
"""Seed LangFuse chat.system prompt with Task 69 placeholders."""

from __future__ import annotations

import sys

from backend.core.prompt_service import DEFAULT_CHAT_SYSTEM, normalize_chat_system_template
from backend.observability.langfuse_client import get_langfuse


def main() -> int:
    lf = get_langfuse()
    if lf is None:
        print("LangFuse unavailable (LANGFUSE_ENABLED=0 or keys missing); skip seed.")
        return 0

    content = normalize_chat_system_template(DEFAULT_CHAT_SYSTEM)
    labels = ["production", "staging"]
    for label in labels:
        try:
            lf.create_prompt(
                name="chat.system",
                prompt=content,
                labels=[label],
                type="text",
            )
            print(f"OK chat.system created/updated label={label}")
        except Exception as exc:
            print(f"WARN chat.system label={label} failed: {exc}")
    try:
        lf.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
