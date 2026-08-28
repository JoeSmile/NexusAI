"""ChannelProvider protocol + inbox + external stubs (Task 44.1)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from backend.database.pgvector_session import Notification

logger = logging.getLogger(__name__)


@runtime_checkable
class ChannelProvider(Protocol):
    name: str

    def available(self) -> bool:
        ...

    def send(
        self,
        session: Session,
        *,
        tenant_id: str,
        user_id: str,
        type: str,
        payload: dict[str, Any],
    ) -> Notification | None:
        ...


class InboxChannel:
    """站内信：写入 notifications 表。"""

    name = "inbox"

    def available(self) -> bool:
        return True

    def send(
        self,
        session: Session,
        *,
        tenant_id: str,
        user_id: str,
        type: str,
        payload: dict[str, Any],
    ) -> Notification:
        row = Notification(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            type=type,
            channel=self.name,
            payload=dict(payload or {}),
            read_at=None,
            created_at=datetime.utcnow(),
        )
        session.add(row)
        return row


class _UnavailableStub:
    """未配置的外部渠道：available=False，注册表可不加载。"""

    def __init__(self, name: str) -> None:
        self.name = name

    def available(self) -> bool:
        return False

    def send(
        self,
        session: Session,
        *,
        tenant_id: str,
        user_id: str,
        type: str,
        payload: dict[str, Any],
    ) -> None:
        return None


class WecomChannel(_UnavailableStub):
    def __init__(self) -> None:
        super().__init__("wecom")


class FeishuChannel(_UnavailableStub):
    def __init__(self) -> None:
        super().__init__("feishu")


class EmailChannel(_UnavailableStub):
    def __init__(self) -> None:
        super().__init__("email")


_providers: dict[str, ChannelProvider] = {}


def register_provider(provider: ChannelProvider) -> None:
    _providers[provider.name] = provider


def clear_providers() -> None:
    _providers.clear()


def ensure_default_providers() -> None:
    """幂等注册 inbox；外部渠道仅占位、不进可用表。"""
    if "inbox" not in _providers:
        register_provider(InboxChannel())


def list_available_providers() -> list[ChannelProvider]:
    ensure_default_providers()
    return [p for p in _providers.values() if p.available()]


def get_provider(name: str) -> ChannelProvider | None:
    ensure_default_providers()
    return _providers.get(name)
