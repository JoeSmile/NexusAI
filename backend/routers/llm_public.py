"""Public LLM model listing for tenant chat (Task 49)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from packages.auth.dual_auth import verify_human_or_legacy_key
from packages.auth.models import TenantContext
from backend.core.llm_credentials import list_available_models

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/available-models")
async def get_available_models(
    tenant: TenantContext = Depends(verify_human_or_legacy_key),
):
    """List models configured for the current tenant."""
    items = await list_available_models(tenant.tenant_id)
    return {"items": items}
