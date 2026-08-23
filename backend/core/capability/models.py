"""Capability 统一数据模型（Task 30.01）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.core.capability.contract import ToolContract


class CapabilityKind(StrEnum):
    MODEL = "model"
    DATASOURCE = "datasource"
    TOOL = "tool"
    WORKFLOW = "workflow"
    EXTERNAL_APP = "external_app"
    AGENT = "agent"


class CapabilityProvider(StrEnum):
    NEXUSAI = "nexusai"
    DIFY = "dify"
    COZE = "coze"
    AI_PLATFORM = "ai-platform"
    SELF_HOSTED = "self-hosted"
    MCP = "mcp"  # Task 66 — external MCP server tools (provider=mcp)


class CapabilityStatus(StrEnum):
    """与 capabilities.status 列一致（005 migration 默认 enabled）。"""

    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass
class CapabilitySpec:
    """注册进 capability registry 的能力描述。"""

    id: str
    name: str
    kind: CapabilityKind
    provider: CapabilityProvider
    spec: dict[str, Any] = field(default_factory=dict)
    status: CapabilityStatus = CapabilityStatus.ENABLED
    cost_model: dict[str, Any] = field(default_factory=dict)
    permission: str = ""
    tenant_id: str = "*"
    # Wave C0: { param_name: {type, required, description?, default?, enum_values?} }
    param_spec: dict[str, Any] | None = None
    # Task 56: 运行时缓存的 ToolContract（从 spec["tool_contract"] 解析）
    contract: ToolContract | None = None

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
        if self.param_spec is not None and not isinstance(self.param_spec, dict):
            self.param_spec = dict(self.param_spec)
