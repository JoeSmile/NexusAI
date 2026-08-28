"""Dual accept: Bearer session OR legacy X-API-Key (Wave A).

Does NOT tighten verify_api_key (no machine-only).
"""

from __future__ import annotations

from fastapi import Header, Security

from packages.auth.api_key_auth import api_key_header, verify_api_key
from packages.auth.models import TenantContext
from packages.auth.session_auth import verify_session


async def verify_human_or_legacy_key(
    authorization: str | None = Header(None),
    api_key: str | None = Security(api_key_header),
) -> TenantContext:
    """1) Bearer → verify_session; 2) else X-API-Key → verify_api_key."""
    if authorization and authorization.lower().startswith("bearer "):
        return await verify_session(authorization=authorization)
    return await verify_api_key(api_key)
