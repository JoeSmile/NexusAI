"""One-shot A4 helper: dump enabled AB variant_configs. Not a product path."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.database.pgvector_session import get_pg_session


def main() -> int:
    sf = get_pg_session()
    with sf.Session() as session:
        rows = session.execute(
            text(
                """
                SELECT experiment_id, name, enabled, extra_metadata
                FROM ab_test_experiments
                WHERE enabled = true
                """
            )
        ).fetchall()
    print(f"enabled_experiments={len(rows)}")
    for row in rows:
        print(f"{row.experiment_id}\t{row.name}\t{row.extra_metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
