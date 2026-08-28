"""Task 45 content ops — hotspot, style dual-track, script.gen."""

from packages.content_ops.style import (
    DEFAULT_CONTENT_STYLE,
    get_content_style,
    list_content_styles,
    resolve_style_for_generate,
    upsert_content_style,
)

__all__ = [
    "DEFAULT_CONTENT_STYLE",
    "get_content_style",
    "list_content_styles",
    "resolve_style_for_generate",
    "upsert_content_style",
]
