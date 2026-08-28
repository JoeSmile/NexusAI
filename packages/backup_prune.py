"""Keep the newest N pg_dump files (Task 52 P0-2)."""

from __future__ import annotations

from pathlib import Path

DEFAULT_KEEP = 14
DEFAULT_GLOB = "nexusai-*.sql.gz"


def prune_backup_dir(
    directory: Path, *, keep: int = DEFAULT_KEEP, pattern: str = DEFAULT_GLOB
) -> list[Path]:
    """Delete older dumps beyond ``keep``. Returns removed paths."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    files = sorted(
        directory.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed: list[Path] = []
    for stale in files[max(0, keep) :]:
        stale.unlink(missing_ok=True)
        removed.append(stale)
    return removed
