"""Capability 错误码（Task 30.01）— 格式对齐 AUTH_001 / LLM_002。"""

from __future__ import annotations

from backend.core.errors import ErrorCode, NexusAIException


class CapabilityNotFoundError(NexusAIException):
    """CAP_001 — 能力不存在。"""

    def __init__(
        self,
        message: str = "capability_not_found",
        detail: str | None = None,
    ) -> None:
        super().__init__(ErrorCode.CAP_NOT_FOUND.value, message, detail)


class CapabilityDisabledError(NexusAIException):
    """CAP_002 — 能力已禁用。"""

    def __init__(
        self,
        message: str = "capability_disabled",
        detail: str | None = None,
    ) -> None:
        super().__init__(ErrorCode.CAP_DISABLED.value, message, detail)


class CapabilityUpstreamError(NexusAIException):
    """CAP_003 — 上游（外部应用/模型端点）失败。"""

    def __init__(
        self,
        message: str = "upstream_error",
        detail: str | None = None,
    ) -> None:
        super().__init__(ErrorCode.CAP_UPSTREAM_ERROR.value, message, detail)


class CapabilityGovernanceRequiredError(NexusAIException):
    """CAP_004 — 治理校验未通过（护栏/权限等）。"""

    def __init__(
        self,
        message: str = "governance_required",
        detail: str | None = None,
    ) -> None:
        super().__init__(ErrorCode.CAP_GOVERNANCE_REQUIRED.value, message, detail)


class CapabilityQuotaExceededError(NexusAIException):
    """CAP_005 — 配额/预算超限。"""

    def __init__(
        self,
        message: str = "quota_exceeded",
        detail: str | None = None,
    ) -> None:
        super().__init__(ErrorCode.CAP_QUOTA_EXCEEDED.value, message, detail)


class CapabilityContractError(NexusAIException):
    """CAP_006 — ToolContract 缺失或非法（注册硬闸）。"""

    def __init__(
        self,
        message: str = "tool_contract_invalid",
        detail: str | None = None,
    ) -> None:
        super().__init__(ErrorCode.CAP_CONTRACT_INVALID.value, message, detail)
