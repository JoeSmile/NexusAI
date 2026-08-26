"""Worker liveness probe for compose healthchecks.

Exits 0 iff the worker's Redis heartbeat is fresh, 1 otherwise (and 2
on usage error). Run INSIDE the worker container:

    python scripts/worker_liveness.py <worker-name> [max_age_seconds]

The worker name must match the WorkerHeartbeat name in
backend/workers/heartbeat.py (e.g. "memory", "social"). Redis
connection comes from REDIS_HOST / REDIS_PORT / REDIS_PASSWORD env
vars, which the compose files already set for every worker service.
"""

from __future__ import annotations

import os
import sys
import time


def main(argv: list[str]) -> int:
    if len(argv) < 1:
        print("usage: worker_liveness.py <worker> [max_age_seconds]", file=sys.stderr)
        return 2
    worker = argv[0]
    try:
        max_age = float(argv[1]) if len(argv) > 1 else 120.0
    except ValueError:
        print("max_age must be a number", file=sys.stderr)
        return 2

    import redis

    r = redis.Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=os.environ.get("REDIS_PASSWORD") or None,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    try:
        r.ping()
    except Exception as exc:  # Redis unreachable → worker cannot work
        print(f"worker={worker} redis unreachable: {exc}", file=sys.stderr)
        return 1

    raw = r.get(f"nexusai:worker:heartbeat:{worker}")
    if not raw:
        print(f"worker={worker} no heartbeat key", file=sys.stderr)
        return 1
    age = time.time() - float(raw)
    if age > max_age:
        print(
            f"worker={worker} stale heartbeat age={age:.0f}s > {max_age:.0f}s",
            file=sys.stderr,
        )
        return 1
    print(f"worker={worker} heartbeat age={age:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
