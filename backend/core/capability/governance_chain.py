"""治理链骨架（Task 56 切片 1）— 叙事序：策略→预算→审批→IAM→审计→放行。

现有 ``governance.py`` 仍管 rate/quota/guards，本模块不改名、不替代护栏。
审批真接线（UI/approval_requests）面试后；本期 stub。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.core.auth.models import TenantContext
from backend.core.capability.contract import derive_idempotency_key
from backend.core.capability.errors import (
    CapabilityQuotaExceededError,
)
from backend.core.capability.models import CapabilitySpec
from backend.core.errors import ErrorCode, NexusAIException

logger = logging.getLogger(__name__)


@dataclass
class DecisionExplain:
    """可解释裁决载荷（切片 5 落库；本期随 deny/allow 返回）。"""

    allowed: bool
    stages: list[dict[str, Any]] = field(default_factory=list)
    idempotency_key: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "stages": list(self.stages),
            "idempotency_key": self.idempotency_key,
            "reason": self.reason,
        }

    def to_detail(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _stage(name: str, decision: str, detail: str = "") -> dict[str, Any]:
    return {"stage": name, "decision": decision, "detail": detail}


def run_governance_chain(
    spec: CapabilitySpec,
    tenant: TenantContext,
    payload: dict[str, Any],
    *,
    check_permission,
) -> DecisionExplain:
    """同步治理链。deny 抛 NexusAIException；allow 返回 DecisionExplain。

    顺序（面试叙事）:
      policy → budget → approval → IAM → audit(explain)
    """
    explain = DecisionExplain(allowed=False)
    if spec.contract is not None:
        explain.idempotency_key = derive_idempotency_key(
            spec.contract,
            tenant_id=tenant.tenant_id,
            payload=payload,
        )

    # 1) policy — sub-agent critical tool block (Task 62)
    from backend.core.auth.subagent import is_sub_agent
    from backend.core.capability.risk import is_critical_capability

    if is_sub_agent(tenant) and is_critical_capability(spec):
        explain.stages.append(
            _stage("policy", "deny", f"sub_agent_critical_blocked:{spec.id}")
        )
        explain.reason = "sub_agent_critical_denied"
        raise NexusAIException(
            ErrorCode.AUTH_INSUFFICIENT_PERMISSIONS.value,
            "sub_agent_critical_denied",
            detail=explain.to_detail(),
        )
    explain.stages.append(_stage("policy", "allow", "policy_ok"))

    # 2) budget — 复用现有 cap rate/quota
    from backend.core.capability.governance import (
        check_cap_quota,
        check_cap_rate_limit,
    )

    try:
        check_cap_rate_limit(tenant.tenant_id)
        check_cap_quota(tenant.tenant_id)
        explain.stages.append(_stage("budget", "allow", "within_quota"))
    except CapabilityQuotaExceededError as exc:
        explain.stages.append(_stage("budget", "deny", str(exc.detail or exc.message)))
        explain.reason = "budget_exceeded"
        raise NexusAIException(
            ErrorCode.CAP_QUOTA_EXCEEDED.value,
            "quota_exceeded",
            detail=explain.to_detail(),
        ) from exc
    except NexusAIException as exc:
        if exc.code == ErrorCode.RATE_LIMITED.value:
            explain.stages.append(
                _stage("budget", "deny", str(exc.detail or exc.message))
            )
            explain.reason = "rate_limited"
            raise NexusAIException(
                ErrorCode.RATE_LIMITED.value,
                "rate_limited",
                detail=explain.to_detail(),
            ) from exc
        raise

    # 3) approval — stub：仅当 spec.requires_approval 为真才拦
    requires_approval = bool(
        isinstance(spec.spec, dict) and spec.spec.get("requires_approval")
    )
    if requires_approval:
        explain.stages.append(_stage("approval", "deny", "approval_required_stub"))
        explain.reason = "approval_required"
        raise NexusAIException(
            ErrorCode.CAP_GOVERNANCE_REQUIRED.value,
            "approval_required",
            detail=explain.to_detail(),
        )
    explain.stages.append(_stage("approval", "allow", "not_required"))

    # 4) IAM — 保留原异常类型（CAP_001/AUTH_002 等），仅附加 explain 到 detail
    try:
        check_permission(spec, tenant)
        explain.stages.append(_stage("iam", "allow", "permission_ok"))
    except NexusAIException as exc:
        explain.stages.append(_stage("iam", "deny", str(exc.detail or exc.message)))
        explain.reason = "iam_denied"
        exc.detail = explain.to_detail()
        raise

    # 5) audit(explain) — 切片 5 落库（invoke → write_governance_audit）
    explain.allowed = True
    explain.reason = "allow"
    explain.stages.append(_stage("audit", "recorded", "decision_explain_ready"))
    logger.debug(
        "governance_chain allow cap=%s tenant=%s stages=%s",
        spec.id,
        tenant.tenant_id,
        explain.stages,
    )
    return explain
