"""47b slice0 — read chat_messages history for workspace chat."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from packages.auth.models import TenantContext
from packages.auth.permissions import require_permission
from backend.database.pgvector_session import ChatMessage, get_pg_session
from backend.logging_config import get_logger

router = APIRouter(prefix="/api/chat", tags=["chat-history"])
logger = get_logger(__name__)


class ChatHistoryItem(BaseModel):
    id: int
    role: str
    content: str
    client_message_id: str | None = None
    created_at: str | None = None


class ChatHistoryResponse(BaseModel):
    items: list[ChatHistoryItem] = Field(default_factory=list)
    has_more: bool = False


_EMPTY_HINT = "还没有历史对话。发一条消息后，可在这里按天回看。"


class ChatTimelineGroup(BaseModel):
    date: str
    count: int
    preview: str = ""
    items: list[ChatHistoryItem] = Field(default_factory=list)


class ChatTimelineResponse(BaseModel):
    groups: list[ChatTimelineGroup] = Field(default_factory=list)
    empty_hint: str = _EMPTY_HINT
    has_more: bool = False


class ChatSearchResponse(BaseModel):
    items: list[ChatHistoryItem] = Field(default_factory=list)


def _item_from_row(r: object) -> ChatHistoryItem:
    created = getattr(r, "created_at", None)
    return ChatHistoryItem(
        id=int(r.id),
        role=str(r.role or ""),
        content=str(r.content or ""),
        client_message_id=getattr(r, "client_message_id", None),
        created_at=created.isoformat() if created else None,
    )


def _like_pattern(needle: str) -> str:
    escaped = (
        (needle or "")
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _scoped_messages(
    session: object,
    *,
    tenant: TenantContext,
    session_id: str,
):
    return session.query(ChatMessage).filter(  # type: ignore[attr-defined]
        ChatMessage.tenant_id == tenant.tenant_id,
        ChatMessage.session_id == session_id,
        ChatMessage.user_id == tenant.user_id,
    )


def _page_rows(
    *,
    tenant: TenantContext,
    session_id: str,
    limit: int,
    before_id: int | None,
) -> tuple[list[object], bool]:
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        q = _scoped_messages(session, tenant=tenant, session_id=session_id)
        if before_id is not None:
            q = q.filter(ChatMessage.id < before_id)
        rows = q.order_by(ChatMessage.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    return rows[:limit], has_more


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


@router.get("/timeline", response_model=ChatTimelineResponse)
async def get_chat_timeline(
    session_id: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, ge=1),
    tenant: TenantContext = Depends(require_permission("chat:write")),
) -> ChatTimelineResponse:
    """Group this user's session messages by UTC date (newest day first).

    Same cursor as ``/history``: newest ``limit`` rows, ``before_id`` for older,
    ``has_more`` via limit+1 probe. A calendar day may split across pages.
    """
    rows, has_more = _page_rows(
        tenant=tenant, session_id=session_id, limit=limit, before_id=before_id
    )
    chronological = list(reversed(rows))
    buckets: dict[str, list[ChatHistoryItem]] = {}
    order: list[str] = []
    for r in chronological:
        created = getattr(r, "created_at", None)
        day = created.date().isoformat() if created else "unknown"
        if day not in buckets:
            buckets[day] = []
            order.append(day)
        buckets[day].append(_item_from_row(r))
    groups = [
        ChatTimelineGroup(
            date=day,
            count=len(buckets[day]),
            preview=(buckets[day][0].content or "")[:80],
            items=buckets[day],
        )
        for day in reversed(order)
    ]
    return ChatTimelineResponse(
        groups=groups, empty_hint=_EMPTY_HINT, has_more=has_more
    )


@router.get("/search", response_model=ChatSearchResponse)
async def search_chat_history(
    session_id: str = Query(..., min_length=1),
    q: str = Query("", max_length=500),
    limit: int = Query(20, ge=1, le=50),
    tenant: TenantContext = Depends(require_permission("chat:write")),
) -> ChatSearchResponse:
    """Keyword (+ optional embedding) search over this user's session history."""
    needle = (q or "").strip()
    if not needle:
        return ChatSearchResponse(items=[])

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        qset = _scoped_messages(
            session, tenant=tenant, session_id=session_id
        ).filter(
            ChatMessage.content.ilike(_like_pattern(needle), escape="\\")
        )
        rows = qset.order_by(ChatMessage.id.asc()).limit(limit).all()
        # Mock sessions ignore ILIKE; keep an in-memory contains filter.
        lowered = needle.lower()
        matched = [
            r
            for r in rows
            if lowered in str(getattr(r, "content", "") or "").lower()
        ]
        seen: set[int] = {int(r.id) for r in matched}

        try:
            from backend.database.embeddings import embed_text

            vec = embed_text(needle, tenant_id=tenant.tenant_id)
            vec_str = "[" + ",".join(str(v) for v in vec) + "]"
            extra = session.execute(
                text(
                    """
                    SELECT id
                    FROM chat_messages
                    WHERE tenant_id = :tid
                      AND user_id = :uid
                      AND session_id = :sid
                      AND embedding IS NOT NULL
                      AND 1 - (embedding <=> CAST(:vec AS vector)) >= :min_score
                    ORDER BY embedding <=> CAST(:vec AS vector)
                    LIMIT :lim
                    """
                ),
                {
                    "tid": tenant.tenant_id,
                    "uid": tenant.user_id,
                    "sid": session_id,
                    "vec": vec_str,
                    "min_score": 0.35,
                    "lim": limit,
                },
            ).fetchall()
            for hit in extra:
                hid = int(hit.id)
                if hid in seen:
                    continue
                row = (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.id == hid,
                        ChatMessage.tenant_id == tenant.tenant_id,
                        ChatMessage.user_id == tenant.user_id,
                        ChatMessage.session_id == session_id,
                    )
                    .first()
                )
                if row is not None:
                    matched.append(row)
                    seen.add(hid)
        except Exception:
            logger.warning(
                "semantic chat search skipped; keyword matches only",
                exc_info=True,
            )

    matched.sort(key=lambda r: int(r.id))
    items = [_item_from_row(r) for r in matched[:limit]]
    return ChatSearchResponse(items=items)


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
