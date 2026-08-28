"""安全护栏"""

from packages.guardrails.base import GuardResult
from packages.guardrails.input_guard import check_input
from packages.guardrails.output_guard import check_output

__all__ = ["GuardResult", "check_input", "check_output"]
