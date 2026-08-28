"""Chat context → LLM messages assembly (Task 69)."""

from __future__ import annotations

from typing import Any

from packages.plan.retrieval_mode import estimate_prompt_tokens
from packages.pipeline.state import PipelineState

HOT_HISTORY_TURNS = 10
CONTEXT_TOKEN_BUDGET = 8000


def resolved_query(state: PipelineState) -> str:
    qr = state.get("query_rewrite")
    if isinstance(qr, dict):
        rq = str(qr.get("rewritten_query") or "").strip()
        if rq:
            return rq
    return str(state.get("message") or "")


def current_user_content(state: PipelineState) -> str:
    """Current-turn user text; honors experiment_hook prefix on assembled_prompt."""
    assembled = (state.get("assembled_prompt") or "").strip()
    if assembled:
        if assembled.startswith("user: "):
            return assembled[6:].strip()
        return assembled
    return resolved_query(state)


def _normalize_hot_role(role: object) -> str:
    raw = str(role or "user").strip().lower()
    if raw in {"assistant", "ai", "bot", "model"}:
        return "assistant"
    return "user"


def expand_hot_messages(
    hot_memory: list[dict[str, Any]] | None,
    *,
    max_turns: int = HOT_HISTORY_TURNS,
    budget_tokens: int = CONTEXT_TOKEN_BUDGET,
) -> list[dict[str, str]]:
    """Expand hot memory into user/assistant messages; trim oldest first."""
    rows: list[dict[str, str]] = []
    for item in hot_memory or []:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        rows.append(
            {
                "role": _normalize_hot_role(item.get("role")),
                "content": content,
            }
        )
    rows = rows[-max_turns:]
    while rows:
        joined = "\n".join(m["content"] for m in rows)
        if estimate_prompt_tokens(joined) <= budget_tokens:
            break
        rows.pop(0)
    return rows


def trim_messages_to_budget(
    messages: list[dict[str, str]],
    *,
    budget_tokens: int = CONTEXT_TOKEN_BUDGET,
) -> list[dict[str, str]]:
    """Keep system + latest user; drop oldest hot turns when over budget."""
    if not messages:
        return messages
    if estimate_prompt_tokens("\n".join(m["content"] for m in messages)) <= budget_tokens:
        return messages
    if len(messages) < 3:
        return messages
    system = messages[0]
    user = messages[-1]
    hot = messages[1:-1]
    while hot:
        candidate = [system, *hot, user]
        if estimate_prompt_tokens("\n".join(m["content"] for m in candidate)) <= budget_tokens:
            break
        hot.pop(0)
    return [system, *hot, user]


def build_llm_messages(
    state: PipelineState,
    *,
    system_template: str,
    memory_block: str | None = None,
) -> list[dict[str, str]]:
    """system + warm/cold memory + hot multi-turn + current user."""
    from packages.prompt_service import render_prompt

    mem = (
        memory_block
        if memory_block is not None
        else str(state.get("memory_prompt_block") or "")
    ).strip()
    hot_msgs = expand_hot_messages(state.get("hot_memory") or [])
    history_note = "（上文多轮对话见消息历史）" if hot_msgs else ""

    system_content = render_prompt(
        system_template,
        {
            "role": "企业助手",
            "memory": mem,
            "history": history_note,
            "context": "",
        },
    )
    if mem and mem not in system_content:
        system_content = f"{system_content}\n\n{mem}".strip()
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(hot_msgs)
    messages.append({"role": "user", "content": current_user_content(state)})
    return trim_messages_to_budget(messages, budget_tokens=CONTEXT_TOKEN_BUDGET)
