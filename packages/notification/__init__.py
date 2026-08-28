"""Multi-channel notification skeleton (Task 44)."""

from __future__ import annotations

from packages.notification.service import (
    mark_read,
    notify,
    notify_many,
    unread_count,
)

__all__ = ["notify", "notify_many", "mark_read", "unread_count"]
