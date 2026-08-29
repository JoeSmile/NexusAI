"""Social API business helpers (Task 52 S3)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.database.pgvector_session import (
    SocialAccount,
    SocialContent,
    SocialFollow,
    SocialResult,
    SocialTask,
)
from packages.content_ops.style import get_org_content_profile
from packages.social.connector import TikHubConnector
from packages.social.exceptions import (
    PlatformNotOpenError,
    SocialCostAlertError,
)
from packages.social.pipeline import fetch_only_marker, upsert_account_from_probe
from packages.social.queue import find_active_task
from packages.social.rate_limit import acquire_for_probe
from packages.social.usage import COST_PROBE, cost_alert_exceeded, record_usage

RETRY_ANALYZE_ONLY = "[retry_analyze_only]"
FETCH_ONLY = "[fetch_only]"
ANALYZE_ALL = "[analyze_all]"


def resolve_brand(
    session: Session,
    tenant_id: str,
    brand: dict[str, Any] | None,
) -> dict[str, str]:
    """Map org-profile → brand; style only from request override."""
    profile = get_org_content_profile(session, tenant_id)
    b = brand or {}
    name = (b.get("name") or profile.get("name") or "").strip()
    business = (
        b.get("business")
        or profile.get("product_focus")
        or profile.get("industry")
        or ""
    ).strip()
    audience = (b.get("audience") or profile.get("target_audience") or "").strip()
    style = (b.get("style") or "").strip()  # request-only
    if not name:
        raise ValueError("请先配置企业画像")
    out = {"name": name, "business": business}
    if audience:
        out["audience"] = audience
    if style:
        out["style"] = style
    return out


def probe_account(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    platform: str,
    account_key: str,
) -> SocialAccount:
    if platform != "douyin":
        raise PlatformNotOpenError(platform)
    acquire_for_probe()
    with TikHubConnector() as conn:
        row = upsert_account_from_probe(
            session,
            platform=platform,
            account_key=account_key.strip(),
            connector=conn,
            acquire=lambda **_: True,  # already acquired
        )
    record_usage(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        platform=platform,
        operation="probe",
        item_count=1,
        cost_usd=COST_PROBE,
    )
    upsert_follow(session, tenant_id=tenant_id, account_id=int(row.id))
    return row


def upsert_follow(
    session: Session,
    *,
    tenant_id: str,
    account_id: int,
) -> SocialFollow:
    row = (
        session.query(SocialFollow)
        .filter(
            SocialFollow.tenant_id == tenant_id,
            SocialFollow.account_id == account_id,
        )
        .one_or_none()
    )
    if row is not None:
        return row
    try:
        with session.begin_nested():
            row = SocialFollow(tenant_id=tenant_id, account_id=account_id)
            session.add(row)
            session.flush()
            return row
    except IntegrityError:
        found = (
            session.query(SocialFollow)
            .filter(
                SocialFollow.tenant_id == tenant_id,
                SocialFollow.account_id == account_id,
            )
            .one()
        )
        return found


def list_followed_accounts(session: Session, *, tenant_id: str) -> list[SocialAccount]:
    return (
        session.query(SocialAccount)
        .join(SocialFollow, SocialFollow.account_id == SocialAccount.id)
        .filter(SocialFollow.tenant_id == tenant_id)
        .order_by(SocialFollow.created_at.desc())
        .all()
    )


def create_analysis_task(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    platform: str,
    account_key: str,
    phase: str = "full",
    fetch_limit: int = 20,
) -> tuple[SocialTask, bool]:
    """Returns (task, created). Duplicate active → existing task.

    phase: fetch=只拉最近一页落库; analyze=只对已入库内容跑口播结构; full=两者连续。
    """
    if platform != "douyin":
        raise PlatformNotOpenError(platform)
    if cost_alert_exceeded(session):
        raise SocialCostAlertError()
    if phase not in ("fetch", "analyze", "full"):
        raise ValueError("invalid_phase")

    key = account_key.strip()
    account = (
        session.query(SocialAccount)
        .filter(SocialAccount.platform == platform, SocialAccount.account_key == key)
        .one_or_none()
    )
    # UI 两步：先 probe 再拉数；禁止隐式 probe（错 id 可改、用户不懵）
    if account is None:
        raise ValueError("请先拉取账号")
    if phase == "analyze":
        has_contents = (
            session.query(SocialContent)
            .filter(SocialContent.account_id == account.id)
            .count()
            > 0
        )
        if not has_contents:
            raise ValueError("请先拉取内容")

    existing = find_active_task(session, tenant_id=tenant_id, user_id=user_id)
    if existing is not None:
        return existing, False

    try:
        with session.begin_nested():
            task = SocialTask(
                tenant_id=tenant_id,
                user_id=user_id,
                platform=platform,
                account_id=account.id,
                status="pending",
                progress=60 if phase == "analyze" else 0,
                error=(
                    fetch_only_marker(fetch_limit)
                    if phase == "fetch"
                    else ANALYZE_ALL
                    if phase == "analyze"
                    else None
                ),
            )
            session.add(task)
            session.flush()
    except IntegrityError:
        existing = find_active_task(session, tenant_id=tenant_id, user_id=user_id)
        if existing is None:
            raise
        return existing, False
    return task, True


def hint_previous_task_id(session: Session, task: SocialTask) -> int | None:
    if (task.new_count or 0) != 0:
        return None
    prev = (
        session.query(SocialTask)
        .filter(
            SocialTask.tenant_id == task.tenant_id,
            SocialTask.account_id == task.account_id,
            SocialTask.status == "done",
            SocialTask.id != task.id,
        )
        .order_by(SocialTask.id.desc())
        .first()
    )
    return int(prev.id) if prev else None


def retry_task(session: Session, task: SocialTask) -> SocialTask:
    if task.status != "failed":
        raise ValueError("only_failed_can_retry")
    # 有账号内容 → 只补缺失 structure；否则整页重拉
    has_contents = (
        session.query(SocialContent)
        .filter(SocialContent.account_id == task.account_id)
        .count()
        > 0
    )
    task.status = "pending"
    task.finished_at = None
    task.leased_at = None
    if has_contents:
        task.progress = 60
        task.error = RETRY_ANALYZE_ONLY
    else:
        task.progress = 0
        task.total_count = 0
        task.new_count = 0
        task.skipped = 0
        task.error = None
    session.flush()
    return task


def list_contents(
    session: Session,
    *,
    account_id: int,
    like_min: int | None = None,
    collect_min: int | None = None,
    duration_min: int | None = None,
    duration_max: int | None = None,
    date_from: Any = None,
    date_to: Any = None,
    has_content: bool | None = None,
) -> list[SocialContent]:
    exists = (
        session.query(SocialAccount.id)
        .filter(SocialAccount.id == account_id)
        .one_or_none()
    )
    if exists is None:
        return []
    q = session.query(SocialContent).filter(SocialContent.account_id == account_id)
    if like_min is not None:
        q = q.filter(SocialContent.like_count >= like_min)
    if collect_min is not None:
        q = q.filter(SocialContent.collect_count >= collect_min)
    if duration_min is not None:
        q = q.filter(SocialContent.duration_s >= duration_min)
    if duration_max is not None:
        q = q.filter(SocialContent.duration_s <= duration_max)
    if date_from is not None:
        q = q.filter(SocialContent.published_at >= date_from)
    if date_to is not None:
        q = q.filter(SocialContent.published_at <= date_to)
    if has_content is True:
        q = q.filter(SocialContent.content.isnot(None), SocialContent.content != "")
    if has_content is False:
        q = q.filter(
            (SocialContent.content.is_(None)) | (SocialContent.content == "")
        )
    return q.order_by(SocialContent.published_at.desc()).all()


def stub_replica(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    content_id: int,
    task_id: int,
    brand: dict[str, str],
) -> SocialResult:
    """Replica = pick template → harness 套品牌. Requires template (S5)."""
    from packages.social.analyze import (
        generate_replica_from_template,
        record_replica_usage,
        run_coro,
    )
    from packages.social.templates import pick_template_for_replica

    task = (
        session.query(SocialTask)
        .filter(SocialTask.id == task_id, SocialTask.tenant_id == tenant_id)
        .one_or_none()
    )
    if task is None:
        raise ValueError("请先完成分析")
    content = (
        session.query(SocialContent).filter(SocialContent.id == content_id).one_or_none()
    )
    if content is None:
        raise ValueError("content_not_found")
    if content.account_id != task.account_id:
        raise ValueError("content_account_mismatch")

    result = (
        session.query(SocialResult)
        .filter(
            SocialResult.task_id == task_id,
            SocialResult.content_id == content_id,
        )
        .one_or_none()
    )
    if result is None:
        # allow replica if tenant has templates from other contents on same task account
        result = SocialResult(task_id=task_id, content_id=content_id)
        session.add(result)
        session.flush()

    tpl = pick_template_for_replica(
        session,
        tenant_id=tenant_id,
        platform=task.platform,
        result=result,
    )
    if tpl is None:
        raise ValueError("暂无可用模版，请先完成结构分析")

    result.template_id = tpl.id
    replica = run_coro(
        generate_replica_from_template(
            tenant_id=tenant_id,
            platform=task.platform,
            brand=brand,
            template_structure=dict(tpl.structure_json or {}),
            source_title=content.title,
            source_preview=(content.content or "")[:400],
        )
    )
    result.replica_json = replica
    tpl.usage_count = int(tpl.usage_count or 0) + 1
    record_replica_usage(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        platform=task.platform,
    )
    session.flush()
    return result


# Back-compat alias used by older call sites / tests
generate_replica = stub_replica
