"""Harness 框架"""

from backend.core.harness.base import Harness, HarnessResult
from backend.core.harness.llm import LLMHarness

__all__ = ["Harness", "HarnessResult", "LLMHarness"]
