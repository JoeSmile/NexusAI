"""S3 — span names for workflow / skill / long path."""

from __future__ import annotations

import inspect

from packages.pipeline.nodes import model_router as mr
from packages.pipeline.nodes import run_skill as rs


def test_span_names_workflow_skill_long() -> None:
    skill_src = inspect.getsource(rs)
    router_src = inspect.getsource(mr)
    assert 'name="pipeline.run_skill"' in skill_src
    assert 'name="pipeline.model_router"' in router_src
    assert '"path": "short"' in inspect.getsource(
        __import__("packages.pipeline.short_path", fromlist=["execute_skill_short_path"])
    )
