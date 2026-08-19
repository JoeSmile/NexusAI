"""47b slice0 — read chat_messages history for workspace chat."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.core.auth.models import TenantContext
from backend.core.auth.permissions import require_permission
from backend.database.pgvector_session import ChatMessage, get_pg_session

router = APIRouter(prefix="/api/chat", tags=["chat-history"])


class ChatHistoryItem(BaseModel):
    id: int
    role: str
    content: str
    client_message_id: str | None = None
    created_at: str | None = None


class ChatHistoryResponse(BaseModel):
    items: list[ChatHistoryItem] = Field(default_factory=list)
    has_more: bool = False


@router.get("/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=200),
    before_id: int | None = Query(None, ge=1),
    tenant: TenantContext = Depends(require_permission("chat:write")),
) -> ChatHistoryResponse:
    """Return recent session messages (oldest-first within the page).

    Cursor: omit ``before_id`` for the newest page; pass ``before_id`` to load
    older rows with ``id < before_id``. ``has_more`` uses limit+1 probe.
    Isolation: strictly ``user_id == current user`` -- 遗留 anonymous 数据不再
    共享(多账号曾互见历史,拍板 08-17 修复),各自历史从新消息开始。
    """
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        q = session.query(ChatMessage).filter(
            ChatMessage.tenant_id == tenant.tenant_id,
            ChatMessage.session_id == session_id,
            ChatMessage.user_id == tenant.user_id,
        )
        if before_id is not None:
            q = q.filter(ChatMessage.id < before_id)
        rows = q.order_by(ChatMessage.id.desc()).limit(limit + 1).all()

    has_more = len(rows) > limit
    page = list(reversed(rows[:limit]))
    items = [
        ChatHistoryItem(
            id=r.id,
            role=r.role,
            content=r.content,
            client_message_id=r.client_message_id,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in page
    ]
    return ChatHistoryResponse(items=items, has_more=has_more)


class ChatNoteBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    client_message_id: str | None = None
    role: str = Field(default="assistant", pattern="^(assistant|user)$")


class ChatNoteResponse(BaseModel):
    ok: bool = True
    client_message_id: str | None = None


@router.post("/notes", response_model=ChatNoteResponse)
async def post_chat_note(
    body: ChatNoteBody,
    tenant: TenantContext = Depends(require_permission("chat:write")),
) -> ChatNoteResponse:
    """Persist a local workflow bubble (dig/script) into chat_messages."""
    import uuid as _uuid

    from backend.core.memory_service import get_unified_memory_service

    cid = body.client_message_id or str(_uuid.uuid4())
    mem = get_unified_memory_service(tenant_id=tenant.tenant_id)
    if body.role == "user":
        await mem.write_turn(
            user_id=tenant.user_id,
            session_id=body.session_id,
            user_message=body.content,
            assistant_message="",
            user_client_message_id=cid,
        )
    else:
        await mem.write_turn(
            user_id=tenant.user_id,
            session_id=body.session_id,
            user_message="",
            assistant_message=body.content,
            assistant_client_message_id=cid,
        )
    return ChatNoteResponse(ok=True, client_message_id=cid)
