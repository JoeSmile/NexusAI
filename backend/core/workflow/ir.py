"""Workflow IR models + param_spec validation (Wave C1)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# 供应链防线：params / 节点字段禁止内联凭据与可执行载荷
_FORBIDDEN_PARAM_KEYS = frozenset(
    {
        "base_url",
        "api_key",
        "api_key_ref",
        "secret",
        "secrets",
        "headers",
        "function",
        "code",
        "callable",
        "executor_fn",
    }
)


class ParamSpec(BaseModel):
    """Capability / IR 侧单参数声明（与 capability.param_spec 条目对齐）。"""

    name: str
    type: Literal["string", "number", "boolean", "enum"] = "string"
    required: bool = False
    enum_values: list[str] | None = None
    description: str | None = None
    default: Any = None


class WorkflowEdge(BaseModel):
    """W8 数据流预留；本 Wave 恒空。"""

    source: str
    target: str


class WorkflowNode(BaseModel):
    node_id: str
    capability_id: str
    kind: Literal["capability"] = "capability"
    params: dict[str, Any] = Field(default_factory=dict)
    requestable: bool = False

    @field_validator("capability_id")
    @classmethod
    def _capability_id_nonempty(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("capability_id required")
        return str(v).strip()

    @field_validator("params")
    @classmethod
    def _no_forbidden_keys(cls, v: dict[str, Any]) -> dict[str, Any]:
        bad = _FORBIDDEN_PARAM_KEYS.intersection(v.keys())
        if bad:
            raise ValueError(f"forbidden param keys: {sorted(bad)}")
        return v


class WorkflowIR(BaseModel):
    ir_schema: str = "1"
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _wave_c_constraints(self) -> WorkflowIR:
        if self.edges:
            raise ValueError("edges must be empty in this wave")
        seen: set[str] = set()
        for node in self.nodes:
            if node.kind != "capability":
                raise ValueError("only kind=capability allowed in this wave")
            if node.node_id in seen:
                raise ValueError(f"duplicate node_id: {node.node_id}")
            seen.add(node.node_id)
        return self


def parse_param_spec_map(raw: dict[str, Any] | None) -> dict[str, ParamSpec]:
    """capability.param_spec dict → ParamSpec by name."""
    if not raw:
        return {}
    out: dict[str, ParamSpec] = {}
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            raise ValueError(f"param_spec[{name}] must be object")
        out[name] = ParamSpec(
            name=name,
            type=meta.get("type", "string"),  # type: ignore[arg-type]
            required=bool(meta.get("required", False)),
            enum_values=meta.get("enum_values"),
            description=meta.get("description"),
            default=meta.get("default"),
        )
    return out


def validate_params_against_spec(
    params: dict[str, Any],
    param_spec: dict[str, Any] | None,
) -> None:
    """
    形状校验：
    - 无 param_spec → params 必须 {}
    - 有 spec → 必填齐全、类型合法、无未知键
    """
    if not param_spec:
        if params:
            raise ValueError("params must be empty when capability has no param_spec")
        return

    specs = parse_param_spec_map(param_spec)
    unknown = set(params) - set(specs)
    if unknown:
        raise ValueError(f"unknown params: {sorted(unknown)}")

    for name, spec in specs.items():
        if name not in params:
            if spec.required and spec.default is None:
                raise ValueError(f"missing required param: {name}")
            continue
        val = params[name]
        _check_type(name, val, spec)


def _check_type(name: str, val: Any, spec: ParamSpec) -> None:
    t = spec.type
    if t == "string":
        if not isinstance(val, str):
            raise ValueError(f"param {name} must be string")
    elif t == "number":
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError(f"param {name} must be number")
    elif t == "boolean":
        if not isinstance(val, bool):
            raise ValueError(f"param {name} must be boolean")
    elif t == "enum":
        if not isinstance(val, str):
            raise ValueError(f"param {name} must be string enum")
        allowed = spec.enum_values or []
        if val not in allowed:
            raise ValueError(f"param {name} must be one of {allowed}")


def validate_ir_capabilities(
    ir: WorkflowIR,
    *,
    get_param_spec,
    capability_exists,
) -> None:
    """
    对每个节点：capability 必须已登记；params 对齐 param_spec。

    get_param_spec(capability_id) -> dict|None
    capability_exists(capability_id) -> bool
    """
    for node in ir.nodes:
        if not capability_exists(node.capability_id):
            raise ValueError(f"unknown capability_id: {node.capability_id}")
        validate_params_against_spec(node.params, get_param_spec(node.capability_id))
