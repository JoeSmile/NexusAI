"""Worker liveness: Redis heartbeat + suicide watchdog (deployment hardening).

Design (single module, two responsibilities that share the same timestamp):

1. RedisHeartbeat.beat()  — called at the top of every worker main-loop
   iteration. Writes `nexusai:worker:heartbeat:<name>` (unix ts, EX TTL)
   at most once per beat_interval. Consumed by compose healthchecks
   (scripts/worker_liveness.py) and by Prometheus-minded ops tooling.
   The key lives in the SAME Redis as the queues, so a stale key means
   "worker cannot reach its own queue broker" — a real liveness signal.

2. Suicide watchdog — a daemon thread started via start(). If the main
   loop stops making progress (stall_timeout exceeded), it calls
   os._exit(1): the container exits, Docker `restart: unless-stopped`
   pulls it back up. This closes the "alive but wedged" gap that a
   healthcheck alone cannot close (a failed healthcheck only marks the
   container unhealthy; it does not restart it).

Why both: restart policy covers process death, queue semantics
(Redis Stream PEL / PG status machine) cover message loss, and the
watchdog covers livelock. The healthcheck is the observable layer for
`docker compose ps` and alerting.
"""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_HEARTBEAT_KEY_PREFIX = "nexusai:worker:heartbeat:"


class WorkerHeartbeat:
    """Per-worker heartbeat writer + stall watchdog.

    Usage (worker main loop)::

        hb = WorkerHeartbeat("memory")
        hb.start()
        while True:
            hb.beat()
            ... consume one batch ...

    `beat()` updates the in-process progress timestamp every call and
    writes Redis at most every beat_interval seconds. The watchdog
    thread kills the process if progress stops for stall_timeout.
    """

    def __init__(
        self,
        name: str,
        *,
        beat_interval: float = 15.0,
        ttl: int = 300,
        stall_timeout: float = 120.0,
    ) -> None:
        self.name = name
        self._key = f"{_HEARTBEAT_KEY_PREFIX}{name}"
        self._beat_interval = beat_interval
        self._ttl = ttl
        self._stall_timeout = stall_timeout
        self._last = time.time()
        self._last_written = 0.0
        self._redis = None
        self._wd: threading.Thread | None = None

    # ── main-loop side ──────────────────────────────────────────────
    def beat(self) -> None:
        now = time.time()
        self._last = now  # always: progress signal for the watchdog
        if now - self._last_written < self._beat_interval:
            return
        try:
            self._get_redis().set(self._key, str(now), ex=self._ttl)
            self._last_written = now
        except Exception:
            # Heartbeat write must never take the worker down; the
            # watchdog + healthcheck will surface a dead broker anyway.
            logger.debug("heartbeat write failed name=%s", self.name, exc_info=True)

    def start(self) -> None:
        if self._wd is not None:
            return
        self._wd = threading.Thread(
            target=self._watchdog_loop,
            name=f"watchdog-{self.name}",
            daemon=True,
        )
        self._wd.start()

    def _watchdog_loop(self) -> None:
        interval = min(self._stall_timeout / 4.0, 15.0)
        while True:
            time.sleep(max(interval, 1.0))
            age = time.time() - self._last
            if age > self._stall_timeout:
                logger.error(
                    "watchdog: worker=%s no progress for %.0fs (>%.0fs); "
                    "exiting for restart",
                    self.name,
                    age,
                    self._stall_timeout,
                )
                os._exit(1)

    # ── internals ───────────────────────────────────────────────────
    def _get_redis(self):
        if self._redis is None:
            import redis

            self._redis = redis.Redis(
                host=os.environ.get("REDIS_HOST", "localhost"),
                port=int(os.environ.get("REDIS_PORT", "6379")),
                password=os.environ.get("REDIS_PASSWORD") or None,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        return self._redis
