"""Task 42 — 结构化记忆条目 schema（Pydantic 严格模式）。"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 平台/外部错误码格式（AUTH_001 或 AUTH-001）
ERROR_CODE_RE = re.compile(r"^[A-Z]+[-_]\d{3}$")
_MAX_TEXT = 500
_MAX_SPAN = 200


class EntityType(StrEnum):
    PERSON = "person"
    ORG = "org"
    SYSTEM = "system"
    PROJECT = "project"
    TERM = "term"


class EntityRelation(StrEnum):
    COLLEAGUE = "同事"
    CUSTOMER = "客户"
    SUPPLIER = "供应商"
    SYSTEM = "系统"
    PROJECT = "项目"
    UNKNOWN = "未知"


class TodoOwnerKind(StrEnum):
    SELF = "self"
    ENTITY = "entity"


class ItemStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class MemoryItemBase(BaseModel):
    """统一字段：type / text / source_span / confidence / status。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: str
    text: Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]
    source_span: Annotated[str, Field(min_length=1, max_length=_MAX_SPAN)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    status: str = "active"


class EntityItem(MemoryItemBase):
    type: Literal["entity"] = "entity"
    name: Annotated[str, Field(min_length=1, max_length=64)]
    entity_type: EntityType
    relation: EntityRelation
    mention_source: Annotated[str, Field(min_length=1, max_length=120)] = "user"
    related: list[str] = Field(default_factory=list)


class ErrorCodeItem(MemoryItemBase):
    type: Literal["error_code"] = "error_code"
    code: Annotated[str, Field(min_length=5, max_length=32)]
    system: str | None = None
    message: str | None = None
    count: Annotated[int, Field(ge=1)] = 1

    @field_validator("code")
    @classmethod
    def _code_format(cls, v: str) -> str:
        v = v.strip().upper()
        if not ERROR_CODE_RE.fullmatch(v):
            raise ValueError("invalid_error_code_format")
        return v


class DecisionItem(MemoryItemBase):
    type: Literal["decision"] = "decision"
    statement: Annotated[str, Field(min_length=2, max_length=_MAX_TEXT)]
    options: list[str] = Field(default_factory=list)
    chosen: str | None = None
    related: list[str] = Field(default_factory=list)


class TodoItem(MemoryItemBase):
    type: Literal["todo"] = "todo"
    action: Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]
    owner: str | None = None
    owner_kind: TodoOwnerKind
    due: str | None = None
    status: Literal["open", "done"] = "open"

    @model_validator(mode="after")
    def _owner_rules(self) -> TodoItem:
        if self.owner_kind == TodoOwnerKind.ENTITY and not (self.owner or "").strip():
            raise ValueError("owner_required_for_entity")
        if self.due is not None and self.due.strip():
            due = self.due.strip()
            if not (
                re.fullmatch(r"\d{4}-\d{2}-\d{2}", due)
                or (len(due) <= 16 and re.search(r"[周天日一二三四五六]|前|后", due))
            ):
                raise ValueError("invalid_due_format")
        return self


MemoryItem = EntityItem | ErrorCodeItem | DecisionItem | TodoItem


def parse_memory_item(data: dict) -> MemoryItem:
    """按 type 分派到具体模型（严格）。"""
    t = data.get("type")
    if t == "entity":
        return EntityItem.model_validate(data)
    if t == "error_code":
        return ErrorCodeItem.model_validate(data)
    if t == "decision":
        return DecisionItem.model_validate(data)
    if t == "todo":
        return TodoItem.model_validate(data)
    raise ValueError(f"unknown_item_type:{t}")
