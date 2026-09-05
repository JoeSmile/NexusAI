"""Shim — implementation lives in packages.search_service.failover (Task 84)."""

from packages.search_service.adapter import SearchAdapterError
from packages.search_service.failover import SearchOutcome, search_with_failover

__all__ = ["SearchAdapterError", "SearchOutcome", "search_with_failover"]
