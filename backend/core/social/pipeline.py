"""Fetch + analyze pipeline for one social_tasks row (Task 52 S2).

S2 analyzer writes a lightweight structure stub (no LLM); S5 replaces with harness.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.core.social.connector import TikHubConnector
from backend.core.social.exceptions import TikHubRateLimitTimeout
from backend.core.social.queue import mark_task
from backend.core.social.rate_limit import acquire_tikhub_token
from backend.core.social.types import Content
from backend.core.social.usage import (
    COST_DETAIL_BATCH,
    COST_FETCH_PAGE,
    COST_PROBE,
    record_usage,
)
from backend.database.pgvector_session import (
    SocialAccount,
    SocialContent,
    SocialResult,
    SocialTask,
)

logger = logging.getLogger(__name__)

# acquire 超时回 pending 的次数上限（拍板 ≤3）
MAX_RATE_LIMIT_RETRIES = 3
FETCH_LIMIT_DEFAULT = 20
FETCH_LIMIT_MAX = 50


def clamp_fetch_limit(n: int) -> int:
    return max(1, min(FETCH_LIMIT_MAX, int(n)))


def fetch_only_marker(limit: int = FETCH_LIMIT_DEFAULT) -> str:
    return f"[fetch_only:{clamp_fetch_limit(limit)}]"


def parse_fetch_limit(error: str | None) -> int:
    raw = error or ""
    if raw.startswith("[fetch_only:"):
        num, _, _ = raw[len("[fetch_only:") :].partition("]")
        try:
            return clamp_fetch_limit(int(num))
        except ValueError:
            return FETCH_LIMIT_DEFAULT
    return FETCH_LIMIT_DEFAULT


def is_fetch_only(error: str | None) -> bool:
    return (error or "").startswith("[fetch_only")


def _rate_limit_retry_cap() -> int:
    import os

    try:
        return max(0, int(os.environ.get("SOCIAL_RATE_LIMIT_RETRIES", "3")))
    except ValueError:
        return MAX_RATE_LIMIT_RETRIES


def _acquire_or_timeout(acquire: Callable[..., bool], **kwargs: Any) -> None:
    if not acquire(**kwargs):
        raise TikHubRateLimitTimeout()


def upsert_account_from_probe(
    session: Session,
    *,
    platform: str,
    account_key: str,
    connector: TikHubConnector,
    acquire: Callable[..., bool] = acquire_tikhub_token,
) -> SocialAccount:
    if not acquire():
        raise TikHubRateLimitTimeout()
    info = connector.probe(platform, account_key)
    row = (
        session.query(SocialAccount)
        .filter(
            SocialAccount.platform == platform,
            SocialAccount.account_key == account_key,
        )
        .one_or_none()
    )
    if row is None:
        row = SocialAccount(platform=platform, account_key=account_key)
        session.add(row)
    row.external_id = info.external_id
    row.nickname = info.nickname
    row.avatar_url = info.avatar_url
    row.follower_count = info.follower_count
    row.total_favorited = info.total_favorited
    row.content_count = info.content_count
    row.last_fetched_at = datetime.now(UTC)
    session.flush()
    return row


def _upsert_content(
    session: Session,
    *,
    account_id: int,
    item: Content,
) -> tuple[SocialContent, bool]:
    """Return (row, inserted). Refresh metrics on conflict."""
    existing = (
        session.query(SocialContent)
        .filter(
            SocialContent.platform == item.platform,
            SocialContent.external_id == item.external_id,
        )
        .one_or_none()
    )
    inserted = existing is None
    row = existing or SocialContent(
        platform=item.platform,
        account_id=account_id,
        external_id=item.external_id,
    )
    if inserted:
        session.add(row)
    row.content_type = item.content_type
    row.title = item.title
    if item.content:
        row.content = item.content
        row.content_source = item.content_source or row.content_source or "desc"
    row.duration_s = item.duration_s
    row.like_count = item.like_count
    row.comment_count = item.comment_count
    row.share_count = item.share_count
    row.collect_count = item.collect_count
    row.published_at = item.published_at
    row.fetched_at = datetime.now(UTC)
    row.raw_json = item.raw or None
    session.flush()
    return row, inserted


def run_fetch_phase(
    session: Session,
    task: SocialTask,
    *,
    connector: TikHubConnector | None = None,
    acquire: Callable[..., bool] = acquire_tikhub_token,
) -> list[int]:
    """Pull recent page, upsert contents. Returns content ids that are new for this run."""
    owns = connector is None
    conn = connector or TikHubConnector()
    try:
        account = session.query(SocialAccount).filter(SocialAccount.id == task.account_id).one()
        mark_task(session, task, progress=15)
        if not account.external_id:
            _acquire_or_timeout(acquire)
            info = conn.probe(task.platform, account.account_key)
            account.external_id = info.external_id
            account.nickname = info.nickname or account.nickname
            account.avatar_url = info.avatar_url or account.avatar_url
            account.follower_count = info.follower_count
            account.total_favorited = info.total_favorited
            account.content_count = info.content_count
            record_usage(
                session,
                tenant_id=task.tenant_id,
                user_id=task.user_id,
                platform=task.platform,
                operation="probe",
                item_count=1,
                cost_usd=COST_PROBE,
            )
            session.flush()

        mark_task(session, task, progress=30)
        _acquire_or_timeout(acquire)
        limit = parse_fetch_limit(task.error)
        items = conn.fetch_recent(
            task.platform,
            account.account_key,
            account.external_id or "",
            enrich=True,
            limit=limit,
        )[:limit]
        mark_task(
            session,
            task,
            progress=40,
            total_count=len(items),
        )
        record_usage(
            session,
            tenant_id=task.tenant_id,
            user_id=task.user_id,
            platform=task.platform,
            operation="fetch",
            item_count=len(items),
            cost_usd=COST_FETCH_PAGE,
        )
        # enrich may have called detail — rough meter
        short = sum(1 for c in items if not c.content or len(c.content) < 100)
        if short:
            record_usage(
                session,
                tenant_id=task.tenant_id,
                user_id=task.user_id,
                platform=task.platform,
                operation="detail",
                item_count=short,
                cost_usd=COST_DETAIL_BATCH,
            )

        mark_task(session, task, progress=55)
        new_ids: list[int] = []
        for item in items:
            if not item.external_id:
                mark_task(session, task, skipped=(task.skipped or 0) + 1)
                continue
            row, inserted = _upsert_content(
                session, account_id=account.id, item=item
            )
            if inserted:
                new_ids.append(int(row.id))
        account.last_fetched_at = datetime.now(UTC)
        mark_task(
            session,
            task,
            progress=60,
            total_count=len(items),
            new_count=len(new_ids),
        )
        session.flush()
        return new_ids
    finally:
        if owns:
            conn.close()


def run_analyze_phase(
    session: Session,
    task: SocialTask,
    new_content_ids: list[int],
    *,
    structure_builder: Callable[[SocialContent], dict[str, Any]] | None = None,
) -> None:
    """S5: harness structure + template precipitation; builder override for tests."""
    from backend.core.social.analyze import (
        analyze_structure,
        record_analysis_usage,
        run_coro,
        stub_structure,
    )
    from backend.core.social.templates import link_result_template

    mark_task(session, task, progress=70)
    n = len(new_content_ids) or 1
    for i, cid in enumerate(new_content_ids):
        content = session.query(SocialContent).filter(SocialContent.id == cid).one()
        existing = (
            session.query(SocialResult)
            .filter(
                SocialResult.task_id == task.id,
                SocialResult.content_id == cid,
            )
            .one_or_none()
        )
        if existing is None:
            existing = SocialResult(task_id=task.id, content_id=cid)
            session.add(existing)

        if structure_builder is not None:
            structure = structure_builder(content)
        else:
            structure = run_coro(
                analyze_structure(
                    tenant_id=task.tenant_id,
                    platform=task.platform,
                    title=content.title,
                    content=content.content,
                )
            )
            if not structure:
                structure = stub_structure(content.content or "")

        existing.structure_json = structure
        link_result_template(
            session,
            result=existing,
            tenant_id=task.tenant_id,
            platform=task.platform,
        )
        record_analysis_usage(
            session,
            tenant_id=task.tenant_id,
            user_id=task.user_id,
            platform=task.platform,
        )
        mark_task(session, task, progress=70 + int(20 * (i + 1) / n))
        session.flush()
    mark_task(session, task, progress=95)


def _account_content_ids(session: Session, account_id: int, *, limit: int = 50) -> list[int]:
    rows = (
        session.query(SocialContent.id)
        .filter(SocialContent.account_id == account_id)
        .order_by(SocialContent.id.desc())
        .limit(limit)
        .all()
    )
    return [int(r[0]) for r in rows]


def _missing_structure_content_ids(session: Session, task: SocialTask) -> list[int]:
    """Account contents that lack structure_json on this task (retry analyze-only)."""
    contents = (
        session.query(SocialContent)
        .filter(SocialContent.account_id == task.account_id)
        .all()
    )
    need: list[int] = []
    for c in contents:
        res = (
            session.query(SocialResult)
            .filter(
                SocialResult.task_id == task.id,
                SocialResult.content_id == c.id,
            )
            .one_or_none()
        )
        if res is None or not res.structure_json:
            need.append(int(c.id))
    return need


def process_task(
    session: Session,
    task: SocialTask,
    *,
    connector: TikHubConnector | None = None,
    acquire: Callable[..., bool] = acquire_tikhub_token,
    structure_builder: Callable[[SocialContent], dict[str, Any]] | None = None,
) -> None:
    task_id = int(task.id)
    try:
        marker = task.error or ""
        analyze_all = marker.startswith("[analyze_all]")
        analyze_only = marker.startswith("[retry_analyze_only]") or analyze_all
        fetch_only = is_fetch_only(marker)
        if analyze_only:
            task.error = None
            new_ids = (
                _account_content_ids(session, int(task.account_id))
                if analyze_all
                else _missing_structure_content_ids(session, task)
            )
            mark_task(
                session,
                task,
                progress=60,
                total_count=len(new_ids),
                new_count=0,
            )
        else:
            new_ids = run_fetch_phase(
                session, task, connector=connector, acquire=acquire
            )
            if fetch_only:
                mark_task(
                    session,
                    task,
                    status="done",
                    progress=100,
                    error="",
                    finish=True,
                )
                session.commit()
                return
        run_analyze_phase(
            session, task, new_ids, structure_builder=structure_builder
        )
        mark_task(session, task, status="done", progress=100, finish=True)
        session.commit()
    except TikHubRateLimitTimeout as exc:
        logger.warning("social task %s rate-limit timeout: %s", task_id, exc)
        session.rollback()
        task = session.query(SocialTask).filter(SocialTask.id == task_id).one()
        nxt = int(task.retry_count or 0) + 1
        cap = _rate_limit_retry_cap()
        if nxt > cap:
            mark_task(
                session,
                task,
                status="failed",
                retry_count=nxt,
                error=f"rate_limit_retries_exceeded({cap})",
                clear_lease=True,
                finish=True,
            )
        else:
            mark_task(
                session,
                task,
                status="pending",
                retry_count=nxt,
                error=f"[rate_limit_requeue:{nxt}/{cap}]",
                clear_lease=True,
                finish=False,
            )
            task.finished_at = None
        session.commit()
    except Exception as exc:
        logger.exception("social task %s failed", task_id)
        session.rollback()
        task = session.query(SocialTask).filter(SocialTask.id == task_id).one()
        mark_task(
            session,
            task,
            status="failed",
            error=str(exc)[:2000],
            clear_lease=True,
            finish=True,
        )
        session.commit()
