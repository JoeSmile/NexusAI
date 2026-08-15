"""Alias — metrics import smoke."""

from backend.core.metrics_memory import record_worker_heartbeat, observe_queue_depth


def test_metrics_callable():
    observe_queue_depth(3)
    record_worker_heartbeat()
