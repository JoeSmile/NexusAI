"""Task 52 P0-2 backup retention."""

from __future__ import annotations

import os
import time
from pathlib import Path

from packages.backup_prune import prune_backup_dir


def test_prune_keeps_newest_14(tmp_path: Path) -> None:
    files = []
    for i in range(16):
        p = tmp_path / f"nexusai-202608{i:02d}.sql.gz"
        p.write_bytes(b"x")
        files.append(p)
    for i, p in enumerate(files):
        ts = time.time() - (len(files) - i) * 10
        os.utime(p, (ts, ts))
    removed = prune_backup_dir(tmp_path, keep=14)
    assert len(removed) == 2
    left = list(tmp_path.glob("nexusai-*.sql.gz"))
    assert len(left) == 14
    newest = max(left, key=lambda p: p.stat().st_mtime)
    assert newest.name == "nexusai-20260815.sql.gz"
