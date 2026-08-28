"""ToolContract — capability 双向契约（Task 56 切片 1）。

对标 Agentium ``tools/contract.py``；注册时硬校验（比 Agentium 更严：
要求非空 ``output_schema``）。运行时 JSON Schema 校验本切片不做。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from packages.capability.models import CapabilityKind, CapabilitySpec

# 硬校验种类（model / datasource / workflow 豁免）
CONTRACT_REQUIRED_KINDS = frozenset(
    {
        CapabilityKind.TOOL,
        CapabilityKind.AGENT,
        CapabilityKind.EXTERNAL_APP,
    }
)


class FailureSemantic(BaseModel):
    """声明式失败语义。"""

    model_config = ConfigDict(extra="forbid")

    retryable: bool = False
    idempotent: bool = False
    requires_compensation: bool = False
    failure_codes: list[str] = Field(default_factory=list)


class ToolContract(BaseModel):
    """挂在 capability 上的静态契约（存 ``spec["tool_contract"]``）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(default="v1", min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    failure_semantics: FailureSemantic = Field(default_factory=FailureSemantic)
    idempotency_key_args: list[str] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)


class ToolContractError(ValueError):
    """契约缺失或非法（register 路径抛出，再包装为 CAP_006）。"""


def parse_tool_contract(raw: Any) -> ToolContract | None:
    """从 ``spec["tool_contract"]`` 解析；非法结构抛 ToolContractError。"""
    if raw is None:
        return None
    if isinstance(raw, ToolContract):
        return raw
    if not isinstance(raw, dict):
        raise ToolContractError("tool_contract_not_object")
    try:
        return ToolContract.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError
        raise ToolContractError(f"tool_contract_invalid:{exc}") from exc


def assert_contract_valid(contract: ToolContract | None, capability_id: str) -> None:
    """注册闸：缺契约 / name 不匹配 / 描述过短 / 无 examples / 空 output_schema。"""
    if contract is None:
        raise ToolContractError(f"tool_contract_missing:{capability_id}")
    if contract.name != capability_id:
        raise ToolContractError(
            f"tool_contract_name_mismatch:{capability_id}!={contract.name}"
        )
    stripped = contract.description.strip()
    if len(stripped) < 12:
        raise ToolContractError(
            f"tool_contract_description_too_short:{capability_id}:{len(stripped)}"
        )
    if not contract.examples:
        raise ToolContractError(f"tool_contract_missing_examples:{capability_id}")
    if not contract.output_schema:
        raise ToolContractError(f"tool_contract_missing_output_schema:{capability_id}")


def contract_required_for(kind: CapabilityKind | str) -> bool:
    k = CapabilityKind(kind) if isinstance(kind, str) else kind
    return k in CONTRACT_REQUIRED_KINDS


def validate_capability_contract(spec: CapabilitySpec) -> None:
    """按 kind 决定是否硬校验；通过后把解析结果写回 ``spec.contract``。"""
    raw = None
    if isinstance(spec.spec, dict):
        raw = spec.spec.get("tool_contract")
    contract = parse_tool_contract(raw)
    if contract_required_for(spec.kind):
        assert_contract_valid(contract, spec.id)
    spec.contract = contract


def derive_idempotency_key(
    contract: ToolContract,
    *,
    tenant_id: str,
    payload: dict[str, Any],
) -> str | None:
    """按 ``idempotency_key_args`` 推导幂等键；无声明则 None。"""
    if not contract.idempotency_key_args:
        return None
    parts = [contract.name, tenant_id]
    for arg in contract.idempotency_key_args:
        parts.append(f"{arg}={payload.get(arg)!r}")
    return "|".join(parts)


def stub_contract_dict(cap_id: str) -> dict[str, Any]:
    """最小合法契约（单测 / 过渡 seed 用）。"""
    return {
        "name": cap_id,
        "version": "v1",
        "description": "stub tool contract for tests and transitional seeds",
        "input_schema": {"type": "object"},
        "output_schema": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
        },
        "failure_semantics": {
            "retryable": True,
            "idempotent": True,
            "requires_compensation": False,
            "failure_codes": [],
        },
        "idempotency_key_args": [],
        "examples": [{"input": {}, "output": {"ok": True}}],
    }
