"""Task 41 — 记忆队列业务 gauge（挂现有 /metrics Prometheus mount）。"""

from __future__ import annotations

import time

from prometheus_client import Counter, Gauge

MEMORY_QUEUE_DEPTH = Gauge("nexusai_memory_queue_depth", "Memory write stream depth")
MEMORY_WORKER_HEARTBEAT = Gauge(
    "nexusai_memory_worker_heartbeat_unixtime", "Last worker heartbeat unix time"
)
MEMORY_BACKLOG_TRIGGERS = Counter(
    "nexusai_memory_backlog_triggers_total", "Times backlog forced sync write"
)
MEMORY_DEGRADED_SECONDS = Counter(
    "nexusai_memory_degraded_seconds_total",
    "Seconds spent in Redis-degraded memory path",
)
MEMORY_DROPPED = Counter(
    "nexusai_memory_dropped_total",
    "Poison memory stream messages dropped after max deliveries",
)


def observe_queue_depth(depth: int | None) -> None:
    if depth is None:
        return
    MEMORY_QUEUE_DEPTH.set(depth)


def record_worker_heartbeat() -> None:
    MEMORY_WORKER_HEARTBEAT.set(time.time())


def record_backlog_trigger() -> None:
    MEMORY_BACKLOG_TRIGGERS.inc()


def record_degraded(seconds: float = 1.0) -> None:
    MEMORY_DEGRADED_SECONDS.inc(max(0.0, float(seconds)))


def record_dropped() -> None:
    MEMORY_DROPPED.inc()
