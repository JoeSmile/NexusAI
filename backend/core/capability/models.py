"""Capability 统一数据模型（Task 30.01）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CapabilityKind(StrEnum):
    MODEL = "model"
    DATASOURCE = "datasource"
    TOOL = "tool"
    WORKFLOW = "workflow"
    EXTERNAL_APP = "external_app"
    AGENT = "agent"


class CapabilityProvider(StrEnum):
    CONTEXTGATE = "contextgate"
    DIFY = "dify"
    COZE = "coze"
    AI_PLATFORM = "ai-platform"
    SELF_HOSTED = "self-hosted"


class CapabilityStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass
class CapabilitySpec:
    """注册进 capability registry 的能力描述。"""

    id: str
    name: str
    kind: CapabilityKind
    provider: CapabilityProvider
    spec: dict[str, Any] = field(default_factory=dict)
    status: CapabilityStatus = CapabilityStatus.ACTIVE
    cost_model: dict[str, Any] = field(default_factory=dict)
    permission: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            self.kind = CapabilityKind(self.kind)
        if isinstance(self.provider, str):
            self.provider = CapabilityProvider(self.provider)
        if isinstance(self.status, str):
            self.status = CapabilityStatus(self.status)
        if self.cost_model is None:
            self.cost_model = {}
        if self.spec is None:
            self.spec = {}
