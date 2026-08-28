"""Workflow IR models + param_spec validation (Wave C1 + Task 40.80 dataflow)."""

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
    """Dataflow edge (40.80 final 4-field shape; no source/target aliases)."""

    from_node_id: str
    from_field: str = "result"
    to_node_id: str
    to_param: str

    @field_validator("from_node_id", "to_node_id", "to_param")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("edge fields must be non-empty")
        return str(v).strip()

    @field_validator("from_field", mode="before")
    @classmethod
    def _default_field(cls, v: Any) -> str:
        s = str(v).strip() if v is not None else ""
        return s or "result"


class WorkflowNode(BaseModel):
    node_id: str
    kind: Literal["capability", "workflow", "agent"] = "capability"
    capability_id: str | None = None
    workflow_id: str | None = None
    agent_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    run_if: str | None = None
    # Wave E: tri-state; default true（S2）
    requestable: Literal["true", "sensitive", "false"] = "true"
    approval_note: str | None = None

    @model_validator(mode="after")
    def _kind_ids(self) -> WorkflowNode:
        kind = self.kind
        cap = (self.capability_id or "").strip() or None
        wf = (self.workflow_id or "").strip() or None
        ag = (self.agent_id or "").strip() or None
        object.__setattr__(self, "capability_id", cap)
        object.__setattr__(self, "workflow_id", wf)
        object.__setattr__(self, "agent_id", ag)
        if kind == "capability":
            if not cap or wf or ag:
                raise ValueError(
                    "kind=capability requires capability_id only"
                )
        elif kind == "workflow":
            if not wf or cap or ag:
                raise ValueError("kind=workflow requires workflow_id only")
        elif kind == "agent":
            if not ag or cap or wf:
                raise ValueError("kind=agent requires agent_id only")
        return self

    @field_validator("requestable", mode="before")
    @classmethod
    def _normalize_requestable(cls, v: Any) -> str:
        from packages.workflow.security_gates import (
            HangGateError,
            normalize_requestable,
        )

        try:
            return normalize_requestable(v)
        except HangGateError as exc:
            raise ValueError(str(exc)) from exc

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
    inputs: dict[str, ParamSpec] = Field(default_factory=dict)
    output_node_id: str | None = None  # 评审 08-14 Minor5:声明出口(缺省=最后 succeeded 节点)

    @model_validator(mode="after")
    def _validate_graph(self) -> WorkflowIR:
        seen: set[str] = set()
        for node in self.nodes:
            if node.node_id in seen:
                raise ValueError(f"duplicate node_id: {node.node_id}")
            seen.add(node.node_id)
        if self.edges:
            from packages.workflow.dataflow import (
                DataflowError,
                validate_edges_static,
            )

            try:
                validate_edges_static(self)
            except DataflowError as exc:
                raise ValueError(f"{exc.code}:{exc}") from exc
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
    *,
    allow_unresolved_refs: bool = False,
) -> None:
    """
    形状校验：
    - 无 param_spec → params 必须 {}
    - 有 spec → 必填齐全、类型合法、无未知键
    - allow_unresolved_refs: 保存期跳过 ${output|input} 字符串类型检查
    """
    if not param_spec:
        if params:
            raise ValueError("params must be empty when capability has no param_spec")
        return

    specs = parse_param_spec_map(param_spec)
    unknown = set(params) - set(specs)
    if unknown:
        raise ValueError(f"unknown params: {sorted(unknown)}")

    from packages.workflow.dataflow import parse_input_ref, parse_output_ref

    for name, spec in specs.items():
        if name not in params:
            if spec.required and spec.default is None:
                raise ValueError(f"missing required param: {name}")
            continue
        val = params[name]
        if allow_unresolved_refs and isinstance(val, str):
            if parse_output_ref(val) or parse_input_ref(val):
                continue
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
    对 capability 节点：capability 必须已登记；params 对齐 param_spec。
    workflow/agent 节点本函数跳过（40.81/40.82 另检）。
    """
    for node in ir.nodes:
        if node.kind != "capability":
            continue
        cid = node.capability_id or ""
        if not capability_exists(cid):
            raise ValueError(f"unknown capability_id: {cid}")
        validate_params_against_spec(
            node.params,
            get_param_spec(cid),
            allow_unresolved_refs=True,
        )
