"""Workflow runner — thin façade over internal execution modules.

Split layout (option B):
- ``runner_shared`` — helpers, constants, exceptions
- ``run_lifecycle`` — start / execute / resume / cancel
- ``node_exec`` — IR ready-driven loop and node handlers
- ``run_parent`` — parent/child wake propagation
- ``run_maintenance`` — startup zombie cleanup
- ``composition`` — composition budget (unchanged)

Test patching (import-time binding):
Symbols imported at module top are bound in the **consumer** module.
Patch the consumer, not only the defining module, e.g.::

    patch("backend.core.workflow.run_lifecycle.rebuild_tenant_context", ...)
    patch("backend.core.workflow.node_exec.invoke", ...)
    patch("backend.core.workflow.runner_shared.write_audit_sync", ...)

Patching ``runner_shared.rebuild_tenant_context`` alone does **not** affect
``run_lifecycle`` code that already imported the name.
``from backend.core.workflow.runner import start_run`` etc. still works.
"""

from __future__ import annotations

from backend.core.audit import write_audit_sync
from packages.capability.invoke import invoke
from packages.capability.registry import get_capability_registry
from backend.core.workflow.node_exec import (
    _child_terminal_outputs,
    _execute_agent_node,
    _execute_ir_ready_driven,
    _execute_node,
    _execute_workflow_node,
)
from backend.core.workflow.run_lifecycle import (
    cancel_run,
    continue_run,
    execute_run,
    resume_run,
    schedule_execute,
    schedule_resume,
    schedule_resume_or_continue,
    start_run,
)
from backend.core.workflow.run_maintenance import mark_zombie_runs_failed
from backend.core.workflow.run_parent import (
    _wake_parent_after_fail,
    recover_waiting_child_parents,
    wake_parent,
)
from backend.core.workflow.runner_shared import (
    MAX_RUNNING_ROOT_RUNS,
    RunSuspended,
    RunWaitingChild,
    _audit,
    _collect_outputs,
    _count_inflight_roots,
    _fail_node_ref,
    _fail_run,
    _http_depth_exceeded,
    _load_node_statuses,
    _mark_node_skipped,
    _notify_run_done,
    _run_inputs_from_context,
    _set_node_status,
    freeze_ir_snapshot,
    idempotency_key,
    rebuild_tenant_context,
)

__all__ = [
    "MAX_RUNNING_ROOT_RUNS",
    "RunSuspended",
    "RunWaitingChild",
    "_audit",
    "_child_terminal_outputs",
    "_collect_outputs",
    "_count_inflight_roots",
    "_execute_agent_node",
    "_execute_ir_ready_driven",
    "_execute_node",
    "_execute_workflow_node",
    "_fail_node_ref",
    "_fail_run",
    "_http_depth_exceeded",
    "_load_node_statuses",
    "_mark_node_skipped",
    "_notify_run_done",
    "_run_inputs_from_context",
    "_set_node_status",
    "_wake_parent_after_fail",
    "cancel_run",
    "continue_run",
    "execute_run",
    "freeze_ir_snapshot",
    "get_capability_registry",
    "idempotency_key",
    "invoke",
    "mark_zombie_runs_failed",
    "rebuild_tenant_context",
    "recover_waiting_child_parents",
    "resume_run",
    "schedule_execute",
    "schedule_resume",
    "schedule_resume_or_continue",
    "start_run",
    "wake_parent",
    "write_audit_sync",
]
