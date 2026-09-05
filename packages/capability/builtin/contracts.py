"""ToolContract builders for builtin capabilities."""

from __future__ import annotations

from typing import Any


def _contract(
    cap_id: str,
    *,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    examples: list[dict[str, Any]],
    retryable: bool = True,
    idempotent: bool = False,
    idempotency_key_args: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": cap_id,
        "version": "v1",
        "description": description,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "failure_semantics": {
            "retryable": retryable,
            "idempotent": idempotent,
            "requires_compensation": False,
            "failure_codes": ["CAP_003", "CAP_005"],
        },
        "idempotency_key_args": list(idempotency_key_args or []),
        "examples": examples,
    }


_OBJ = {"type": "object"}
_STR = {"type": "string"}


def rag_search_contract() -> dict[str, Any]:
    return _contract(
        "rag.search",
        description="Search tenant knowledge base documents and return grounded snippets.",
        input_schema={
            "type": "object",
            "properties": {"query": _STR, "search_k": {"type": "integer"}},
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "answer": _STR,
                "sources": {"type": "array"},
                "knowledge_count": {"type": "integer"},
            },
        },
        examples=[
            {
                "input": {"query": "报销流程是什么", "search_k": 3},
                "output": {"answer": "...", "sources": [], "knowledge_count": 1},
            }
        ],
        retryable=True,
        idempotent=True,
        idempotency_key_args=["query"],
    )


def web_search_contract() -> dict[str, Any]:
    return _contract(
        "web.search",
        description="Web search via search_service (query only). Result URLs are display, not fetched.",
        input_schema={
            "type": "object",
            "properties": {"query": _STR, "url": _STR},
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {"results": {"type": "array"}, "query": _STR},
        },
        examples=[
            {
                "input": {"query": "NexusAI capability registry"},
                "output": {"results": [], "query": "NexusAI capability registry"},
            }
        ],
        retryable=True,
        idempotent=True,
        idempotency_key_args=["query"],
    )


def memory_search_contract() -> dict[str, Any]:
    return _contract(
        "memory.search",
        description="Search user warm memories by semantic query for context injection.",
        input_schema={
            "type": "object",
            "properties": {"query": _STR, "limit": {"type": "integer"}},
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {"items": {"type": "array"}},
        },
        examples=[
            {"input": {"query": "上周会议"}, "output": {"items": []}},
        ],
        idempotent=True,
        idempotency_key_args=["query"],
    )


def memory_write_contract() -> dict[str, Any]:
    return _contract(
        "memory.write",
        description="Write a warm memory key-value pair for the current user session.",
        input_schema={
            "type": "object",
            "properties": {"key": _STR, "value": _STR},
            "required": ["key", "value"],
        },
        output_schema={
            "type": "object",
            "properties": {"id": {"type": ["string", "null"]}, "key": _STR},
        },
        examples=[
            {"input": {"key": "pref.lang", "value": "zh"}, "output": {"id": "1", "key": "pref.lang"}},
        ],
        idempotent=True,
        idempotency_key_args=["key", "value"],
    )


def generic_contract(
    cap_id: str,
    *,
    description: str,
    input_props: dict[str, Any] | None = None,
    required: list[str] | None = None,
    idempotent: bool = False,
    idempotency_key_args: list[str] | None = None,
) -> dict[str, Any]:
    return _contract(
        cap_id,
        description=description,
        input_schema={
            "type": "object",
            "properties": input_props or {},
            "required": required or [],
        },
        output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}, "data": _OBJ},
        },
        examples=[{"input": {}, "output": {"ok": True, "data": {}}}],
        idempotent=idempotent,
        idempotency_key_args=idempotency_key_args,
    )
