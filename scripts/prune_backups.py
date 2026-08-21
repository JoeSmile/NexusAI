"""CLI: prune NexusAI pg_dump backups. Used by deploy/backup.sh."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.backup_prune import DEFAULT_KEEP, prune_backup_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune NexusAI pg_dump backups")
    parser.add_argument("--dir", required=True)
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    args = parser.parse_args()
    prune_backup_dir(Path(args.dir), keep=args.keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
