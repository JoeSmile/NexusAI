"""Channel inbound protocol (Task 44.4) — adapters land per platform."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class InboundMessage:
    platform: str
    chat_id: str
    sender: str
    text: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    conversation_id: str = ""

    def __post_init__(self) -> None:
        if not self.conversation_id:
            self.conversation_id = f"{self.platform}:{self.chat_id}"


class ChannelAdapter(Protocol):
    platform: str

    def verify_signature(self, headers: dict[str, str], body: bytes) -> bool: ...

    def parse(self, body: bytes) -> InboundMessage | None: ...
