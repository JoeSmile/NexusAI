"""Skill short-path node — skips build_context (S3)."""

from __future__ import annotations

from packages.observability.decorators import observe
from packages.pipeline.short_path import execute_skill_short_path
from packages.pipeline.state import PipelineState


@observe(name="pipeline.run_skill")
async def run_skill(state: PipelineState) -> PipelineState:
    return await execute_skill_short_path(state)
