"""PlanIR 强类型模型（Task 56 · 编排 P1）。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlanStepMode(StrEnum):
    PARALLEL = "parallel"
    SERIAL = "serial"
    CONDITIONAL = "conditional"


class OnFailMode(StrEnum):
    RETRY = "retry"
    REPLAN = "replan"
    SKIP = "skip"
    FAIL = "fail"


class PlanStepRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max: int = Field(default=2, ge=0, le=8)
    backoff_s: float = Field(default=1.0, ge=0.0, le=60.0)


class PlanStep(BaseModel):
    """Single executable step — L1 sub-task intent = capability_id + sub_query."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    capability_id: str = Field(min_length=1)
    """L1: sub-task intent target (governed by validator whitelist + permissions)."""
    sub_query: str | None = Field(default=None, max_length=2000)
    """L1: natural-language sub-intent for this step; merged into invoke params as message."""
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    mode: PlanStepMode = PlanStepMode.SERIAL
    on_fail: OnFailMode = OnFailMode.FAIL
    retry: PlanStepRetry | None = None
    post_process: list[str] = Field(default_factory=list)
    decision: str | None = None

    @field_validator("depends_on")
    @classmethod
    def _depends_unique(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("depends_on must be unique")
        return v


class CorefEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1, max_length=32)
    canonical: str = Field(min_length=1, max_length=256)
    mentions: list[str] = Field(default_factory=list, max_length=16)
    resolved_value: str = Field(min_length=1, max_length=256)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_turn: int = Field(default=0, ge=0)


class CorefTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[CorefEntry] = Field(default_factory=list, max_length=20)


class QueryRewrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rewritten_query: str = Field(min_length=1, max_length=2000)
    sub_queries: list[str] = Field(default_factory=list)
    language: str = Field(default="zh", max_length=16)
    clarification_needed: bool = False
    suggested_intent: str | None = Field(default=None, max_length=64)
    coref_table: CorefTable | None = None


class PlanIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(default="", max_length=2000)
    steps: list[PlanStep] = Field(min_length=1, max_length=32)
    max_depth: int = Field(default=3, ge=1, le=3)
    version: Literal[1] = 1
    query_rewrite: QueryRewrite | None = None


def normalize_plan_dict(
    raw: dict[str, Any],
    *,
    fallback_goal: str = "",
) -> dict[str, Any]:
    """将 LLM 输出 / 旧版线性 plan 升级为 PlanIR 形状（仍返回 dict）。"""
    data = dict(raw)
    if not data.get("goal"):
        data["goal"] = (fallback_goal or "")[:2000]
    data.setdefault("version", 1)
    data.setdefault("max_depth", 3)
    steps_in = data.get("steps")
    if not isinstance(steps_in, list):
        raise ValueError("task_plan.steps must be a non-empty list")
    steps_out: list[dict[str, Any]] = []
    for i, step in enumerate(steps_in):
        if not isinstance(step, dict):
            raise ValueError(f"step[{i}] must be object")
        s = dict(step)
        if not s.get("id"):
            s["id"] = f"s{i + 1}"
        s.setdefault("depends_on", [])
        s.setdefault("mode", "serial")
        s.setdefault("on_fail", "fail")
        s.setdefault("params", {})
        s.setdefault("post_process", [])
        steps_out.append(s)
    data["steps"] = steps_out
    qr = data.get("query_rewrite")
    if isinstance(qr, dict) and qr.get("rewritten_query"):
        subs = qr.get("sub_queries") or []
        if subs and isinstance(subs[0], dict):
            qr = dict(qr)
            qr["sub_queries"] = [
                str(x.get("query") or x.get("id") or "") for x in subs if isinstance(x, dict)
            ]
            data["query_rewrite"] = qr
    return data


def plan_to_state_dict(plan: PlanIR) -> dict[str, Any]:
    return plan.model_dump(mode="json")
