"""Slash-command gate — auth 之后、preprocess 之前（Task 78.4 / P9）。"""

from __future__ import annotations

import logging
import re

from packages.intent.belief_store import delete_belief, get_belief
from packages.memory.context_summarize import l1_warm_key
from packages.memory.hard_reset import session_hard_reset
from packages.memory.memory_service import get_unified_memory_service
from packages.observability.decorators import observe
from packages.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "可用命令：\n"
    "/reset — 清空本会话未归档对话与滚动摘要，保留当前任务槽位\n"
    "/new — 新开对话并清空任务槽位（长期记忆保留）\n"
    "/context — 查看未归档轮数、是否有摘要、任务是否进行中\n"
    "/help — 显示本说明\n"
    "/feedback <内容> — 提交反馈"
)
_CMD = re.compile(r"^/([A-Za-z]{1,16})(?:\s+(.*))?$", re.DOTALL)
_ALLOWED = frozenset({"reset", "new", "context", "help", "feedback"})
FEEDBACK_MAX = 200
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def parse_slash_command(text: str) -> tuple[str, str] | None:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None
    match = _CMD.match(raw)
    if not match:
        return ("help", "")
    name = match.group(1).lower()
    args = _CTRL.sub("", match.group(2) or "").strip()[:500]
    return name, args


def route_after_command(state: PipelineState) -> str:
    if state.get("finish_reason") == "command_result":
        return "end"
    return "continue"


def _finish(
    state: PipelineState,
    *,
    cmd: str,
    text: str,
    code: str = "ok",
) -> PipelineState:
    state["finish_reason"] = "command_result"
    state["response"] = text
    state["cache_bypass"] = True
    state.setdefault("command", cmd)  # type: ignore[typeddict-item]
    _audit(state, cmd=cmd, code=code)
    return state


def _audit(state: PipelineState, *, cmd: str, code: str) -> None:
    try:
        from packages.audit import write_audit_sync

        write_audit_sync(
            {
                "tenant_id": state["tenant_id"],
                "user_id": state["user_id"],
                "action": "pipeline.slash_command",
                "trace_id": str(state.get("trace_id") or ""),
                "input_text": cmd[:32],
                "output_text": code[:64],
                "model": "",
                "error_code": None if code == "ok" else code,
            }
        )
    except Exception:
        logger.debug("slash command audit skipped", exc_info=True)


def _do_reset(state: PipelineState) -> PipelineState:
    session_hard_reset(state["tenant_id"], state["user_id"], state["session_id"])
    return _finish(state, cmd="reset", text="已清空本会话叙事。当前任务槽位仍保留。")


def _do_new(state: PipelineState) -> PipelineState:
    delete_belief(state["tenant_id"], state["user_id"], state["session_id"])
    session_hard_reset(state["tenant_id"], state["user_id"], state["session_id"])
    return _finish(state, cmd="new", text="已新开对话。任务槽位已清空，长期记忆仍保留。")


async def _do_context(state: PipelineState) -> PipelineState:
    tenant_id = state["tenant_id"]
    user_id = state["user_id"]
    session_id = state["session_id"]
    turns = 0
    has_summary = False
    try:
        mem = get_unified_memory_service(tenant_id=tenant_id)
        bundle = await mem.read(
            user_id=user_id,
            session_id=session_id,
            include_warm=True,
            include_cold=False,
        )
        turns = len(bundle.hot or [])
        raw = str((bundle.warm or {}).get(l1_warm_key(session_id)) or "")
        has_summary = bool(raw.strip())
    except Exception:
        logger.debug("slash /context memory read skipped", exc_info=True)
    belief = get_belief(tenant_id, user_id, session_id)
    status = "IDLE"
    if isinstance(belief, dict):
        status = str(belief.get("status") or "IDLE")
    lines = [
        f"未归档轮数：{turns}",
        f"滚动摘要：{'有' if has_summary else '无'}",
        f"任务状态：{status}",
    ]
    return _finish(state, cmd="context", text="\n".join(lines))


def _do_feedback(state: PipelineState, args: str) -> PipelineState:
    comment = _CTRL.sub("", args).strip()[:FEEDBACK_MAX]
    if not comment:
        return _finish(
            state,
            cmd="feedback",
            text="用法：/feedback <内容>",
            code="empty",
        )
    try:
        from packages.database import DatabaseManager

        with DatabaseManager() as db:
            db.save_feedback(
                session_id=state["session_id"],
                user_id=state["user_id"],
                message_id=None,
                feedback_type="other",
                rating=None,
                comment=comment,
                user_message=str(state.get("raw_input") or "")[:200],
                bot_response="",
                tenant_id=state["tenant_id"],
                client_message_id=None,
            )
    except Exception:
        logger.debug("slash /feedback save failed", exc_info=True)
        return _finish(state, cmd="feedback", text="反馈未能保存，请稍后重试。", code="error")
    return _finish(state, cmd="feedback", text="已收到反馈，感谢。")


@observe(name="pipeline.command_gate")
async def command_gate(state: PipelineState) -> PipelineState:
    raw = str(state.get("raw_input") or state.get("message") or "")
    parsed = parse_slash_command(raw)
    if parsed is None:
        return state
    name, args = parsed
    if name not in _ALLOWED:
        return _finish(state, cmd=name, text=HELP_TEXT, code="unknown")
    if name == "help":
        return _finish(state, cmd="help", text=HELP_TEXT)
    if name == "reset":
        return _do_reset(state)
    if name == "new":
        return _do_new(state)
    if name == "context":
        return await _do_context(state)
    if name == "feedback":
        return _do_feedback(state, args)
    return _finish(state, cmd=name, text=HELP_TEXT, code="unknown")
