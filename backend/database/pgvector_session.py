"""
pgvector 数据库会话管理 + ORM 模型。

所有模型继承 Base，统一管理。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

# BigInteger PK on PG; Integer+autoincrement on SQLite (unit tests)
_PK = BigInteger().with_variant(Integer, "sqlite")


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True)
    session_id = Column(String(100), unique=True, nullable=False, index=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    user_id = Column(String(100), nullable=False, index=True)
    title = Column(Text)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    session_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(100), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    # 47b I1: FE UUID; history returns as-is for feedback hydrate
    client_message_id = Column(String(64), nullable=True, index=True)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_messages_tenant_session", "tenant_id", "session_id"),
    )


class UserMemory(Base):
    __tablename__ = "user_memories"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    user_id = Column(String(100), nullable=False, index=True)
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0)
    source = Column(String(50), default="extracted")
    summary_meta = Column(JSON, nullable=True)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "key"),)


class ColdMemory(Base):
    __tablename__ = "cold_memories"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    user_id = Column(String(100), nullable=False, index=True)
    session_id = Column(String(100))
    summary = Column(Text, nullable=False)
    summary_meta = Column(JSON, nullable=True)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    trace_id = Column(String(100))
    input_text = Column(Text)
    output_text = Column(Text)
    model = Column(String(100), default="")
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)
    error_code = Column(String(50))
    ip_address = Column(String(50), default="")
    user_agent = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    # I-1(评审 08-15)：异步记忆审计去重键（唯一索引见 alembic 018）
    dedupe_key = Column(String(64), nullable=True)
    # Wave A scaffold (nullable; no backfill)
    credential_kind = Column(String(32), nullable=True)
    key_id = Column(String(100), nullable=True)
    run_id = Column(String(100), nullable=True)
    node_id = Column(String(100), nullable=True)
    parent_trace_id = Column(String(100), nullable=True)
    tool_use_id = Column(String(100), nullable=True)
    decision_explain = Column(Text, nullable=True)
    modality = Column(String(32), nullable=True)
    image_hash = Column(String(64), nullable=True)
    input_text_enc = Column(Text, nullable=True)
    output_text_enc = Column(Text, nullable=True)
    text_enc_version = Column(Integer, default=0)
    __table_args__ = (
        Index("idx_audit_tenant_time", "tenant_id", "created_at"),
    )


class UsageRecord(Base):
    """Append-only billing meter (Task 55) — not coupled to audit retention."""

    __tablename__ = "usage_records"
    id = Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(100), nullable=False)
    trace_id = Column(String(100), nullable=True)
    credential_kind = Column(String(32), nullable=False, default="company")
    key_id = Column(String(100), nullable=True)
    model = Column(String(100), nullable=False)
    provider = Column(String(64), nullable=False, default="default")
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost = Column(Numeric(14, 6), nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="CNY")
    billing_month = Column(String(7), nullable=False)
    idempotency_key = Column(String(128), nullable=False, unique=True)
    modality = Column(String(32), nullable=True, default="text")
    image_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("ix_usage_records_tenant_month", "tenant_id", "billing_month"),
        Index("ix_usage_records_tenant_created", "tenant_id", "created_at"),
    )


class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, unique=True, index=True)
    balance = Column(Numeric(14, 4), nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="CNY")
    version = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id = Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, index=True)
    type = Column(String(16), nullable=False)
    amount = Column(Numeric(14, 4), nullable=False)
    balance_after = Column(Numeric(14, 4), nullable=False)
    method = Column(String(32), nullable=False, default="manual")
    reference_no = Column(String(128), nullable=True)
    operator = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("ix_wallet_tx_tenant_created", "tenant_id", "created_at"),
    )


class TermsVersion(Base):
    __tablename__ = "terms_versions"
    id = Column(_PK, primary_key=True, autoincrement=True)
    version = Column(String(32), nullable=False)
    kind = Column(String(32), nullable=False)
    effective_at = Column(DateTime, default=datetime.utcnow)
    content_md = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("kind", "version", name="uq_terms_versions_kind_version"),
        Index("ix_terms_versions_kind_effective", "kind", "effective_at"),
    )


class TermsAcceptance(Base):
    __tablename__ = "terms_acceptances"
    id = Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(100), nullable=False)
    kind = Column(String(32), nullable=False)
    version = Column(String(32), nullable=False)
    accepted_at = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(50), nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "kind",
            "version",
            name="uq_terms_acceptances_user_kind_version",
        ),
        Index("ix_terms_acceptances_tenant_user", "tenant_id", "user_id"),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, index=True)
    user_id = Column(String(100), nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False)
    key_prefix = Column(String(8))
    role = Column(String(32), nullable=False, default="user")
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    description = Column(Text, default="")
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    access_key_id = Column(String(64), unique=True, nullable=True)
    access_key_secret = Column(Text, nullable=True)
    signature_enabled = Column(Boolean, default=False)
    signature_key_version = Column(Integer, default=1)
    # Wave A scaffold (nullable; no backfill; do not reject by type)
    credential_type = Column(String(32), nullable=True)
    created_by_user_id = Column(String(100), nullable=True)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(32), unique=True, nullable=False)
    permissions = Column(JSON, nullable=False)
    description = Column(Text, default="")


class UserAppPerm(Base):
    __tablename__ = "user_app_perms"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False)
    user_id = Column(String(100), nullable=False)
    permissions = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    user_id = Column(String(128), nullable=False)
    resource = Column(String(256), nullable=False)
    resource_type = Column(String(32), nullable=False, default="permission")
    action = Column(String(64), nullable=False)
    params = Column(JSON, default=dict)
    status = Column(String(16), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    timeout_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(128), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_reason = Column(Text, nullable=True)
    __table_args__ = (
        Index("idx_apr_tenant_status", "tenant_id", "status"),
    )


class CacheEntry(Base):
    __tablename__ = "cache_entries"
    id = Column(Integer, primary_key=True)
    cache_key = Column(String(256), unique=True, nullable=False, index=True)
    cache_type = Column(String(20), nullable=False)
    tenant_id = Column(String(50), nullable=False)
    value = Column(Text, nullable=False)
    ttl_seconds = Column(Integer, default=300)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class TenantConfig(Base):
    __tablename__ = "tenant_config"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), unique=True, nullable=False)
    config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LlmApiKey(Base):
    __tablename__ = "llm_api_keys"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    key_alias = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=False)
    base_url = Column(String(256), default="")
    encrypted_key = Column(Text, nullable=False)
    key_version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    last_verified = Column(DateTime, nullable=True)
    last_verified_ok = Column(Boolean, nullable=True)
    last_failed_at = Column(DateTime, nullable=True)  # Task 27: 冷却依据
    consecutive_failures = Column(Integer, default=0, nullable=False)  # Task 27: 摘除依据
    description = Column(Text, default="")
    created_by = Column(String(128))
    allowed_models = Column(JSON, default=list, nullable=False)
    owner_user_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    rotated_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("tenant_id", "key_alias"),
        Index("idx_lak_tenant", "tenant_id", "is_active"),
    )


class Capability(Base):
    """Capability Registry 持久化（Task 30.02 / alembic 005）。"""

    __tablename__ = "capabilities"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, default="*", index=True)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False)
    spec = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=False, default="enabled")
    cost_model = Column(JSON, nullable=False, default=dict)
    permission = Column(Text, nullable=True)
    # Wave C0: workflow 节点参数声明（编辑器 / IR 校验）
    param_spec = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Workflow(Base):
    """Workflow 定义（Wave C / alembic 010）。"""

    __tablename__ = "workflows"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    org_unit_id = Column(String(36), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    ir_json = Column(JSON, nullable=False, default=dict)
    version = Column(Text, nullable=False, default="V1.0.0")
    revision = Column(Integer, nullable=False, default=0)
    forked_from_id = Column(String(36), nullable=True)
    created_by = Column(String(64), nullable=False)
    # Wave E: {scope, default_ttl_days, auto_renew}
    request_policy = Column(JSON, nullable=True)
    intent_tags = Column(JSON, nullable=True)  # Task 40.86 Chat bridge match
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowRun(Base):
    """Workflow 运行实例（Wave D / alembic 011）。"""

    __tablename__ = "workflow_runs"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    workflow_id = Column(String(36), nullable=False, index=True)
    org_unit_id = Column(String(36), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending")
    ir_snapshot = Column(JSON, nullable=False, default=dict)
    workflow_version = Column(Text, nullable=False, default="V1.0.0")
    workflow_revision = Column(Integer, nullable=False, default=0)
    context_ref = Column(JSON, nullable=True)
    parent_run_id = Column(String(36), nullable=True, index=True)
    parent_node_id = Column(String(128), nullable=True)
    composition_depth = Column(Integer, nullable=False, default=0)
    run_inputs = Column(JSON, nullable=True)
    acting_user_id = Column(String(64), nullable=False)
    credential_kind = Column(String(32), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class WorkflowRunNode(Base):
    """Workflow 运行节点（Wave D）。"""

    __tablename__ = "workflow_run_nodes"
    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), nullable=False, index=True)
    node_id = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    attempt = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String(200), nullable=False, unique=True)
    output_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class PermissionRequest(Base):
    """挂起审批申请（Wave E / alembic 012）。"""

    __tablename__ = "permission_requests"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    run_id = Column(String(36), nullable=False, index=True)
    node_id = Column(String(128), nullable=False)
    applicant_user_id = Column(String(64), nullable=False)
    needed_perm = Column(String(128), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    capability_id = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    escalated_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(64), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_reason = Column(Text, nullable=True)
    approval_note = Column(Text, nullable=True)
    requestable_mode = Column(String(16), nullable=False, default="true")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        Index(
            "ix_permission_requests_pending_unique",
            "run_id",
            "node_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )


class WorkflowGrant(Base):
    """Workflow 级授权凭证（Wave E / alembic 012）。"""

    __tablename__ = "workflow_grants"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    request_id = Column(String(36), nullable=False, unique=True)
    workflow_id = Column(String(36), nullable=False)
    scope = Column(String(32), nullable=False, default="recurring")
    applicant_user_id = Column(String(64), nullable=False)
    caps = Column(JSON, nullable=False, default=list)
    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    origin = Column(String(80), nullable=False, default="approval")
    __table_args__ = (
        Index(
            "ix_workflow_grants_tenant_wf",
            "tenant_id",
            "workflow_id",
        ),
        Index(
            "ix_workflow_grants_applicant",
            "tenant_id",
            "applicant_user_id",
            "workflow_id",
        ),
    )


class ScheduledRun(Base):
    """定时执行计划（E3.4 / alembic 017）。"""

    __tablename__ = "scheduled_runs"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    workflow_id = Column(String(36), nullable=False, index=True)
    cron = Column(String(64), nullable=False)
    next_run_at = Column(DateTime, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    run_inputs = Column(JSON, nullable=True)
    org_unit_id = Column(String(64), nullable=False)  # F2(评审 08-15):创建时快照 workflow org
    created_by = Column(String(64), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index(
            "ix_scheduled_runs_due",
            "enabled",
            "next_run_at",
        ),
    )


class Notification(Base):
    """站内信 / 多渠道通知（Task 44 / alembic 014）。"""

    __tablename__ = "notifications"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    user_id = Column(String(64), nullable=False)
    type = Column(String(64), nullable=False)
    channel = Column(String(20), nullable=False, default="inbox")
    payload = Column(JSON, nullable=False, default=dict)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index(
            "ix_notifications_tenant_user_read",
            "tenant_id",
            "user_id",
            "read_at",
        ),
        Index(
            "ix_notifications_tenant_user_created",
            "tenant_id",
            "user_id",
            "created_at",
        ),
    )


class SkillAsset(Base):
    """规划器 CoT 缓存资产（Task 43 / alembic 015）。"""

    __tablename__ = "skill_assets"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    owner_user_id = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=False, default="")
    cot_template = Column(Text, nullable=False, default="")
    ir_skeleton = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="draft")
    visibility = Column(String(32), nullable=False, default="private")
    usage_stats = Column(JSON, nullable=False, default=dict)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        Index(
            "ix_skill_assets_published_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
    )


class KnowledgeChunk(Base):
    """RAG 知识块 — 替代 Chroma knowledge collection"""

    __tablename__ = "knowledge_chunks"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(50), nullable=False, default="default", index=True)
    category = Column(String(100), default="general", index=True)
    content = Column(Text, nullable=False)
    source = Column(String(256), default="")
    source_type = Column(String(32), default="text", index=True)  # text|pdf|audio|image
    meta = Column(JSON, default=dict)
    embedding = Column(Vector(1536), nullable=True)
    org_unit_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class OrgUnit(Base):
    """部门树节点（Wave B / alembic 008）。"""

    __tablename__ = "org_units"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(50), nullable=False, index=True)
    parent_id = Column(String(36), nullable=True)
    name = Column(String(200), nullable=False)
    path = Column(String(1024), nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_org_units_tenant_path", "tenant_id", "path"),)


class OrgMembership(Base):
    """用户 ↔ 部门兼岗 + 业务角色（Wave B）。"""

    __tablename__ = "org_memberships"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(50), nullable=False)
    user_id = Column(String(100), nullable=False)
    org_unit_id = Column(String(36), nullable=False)
    is_primary = Column(Boolean, nullable=False, default=False)
    business_roles = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "org_unit_id", name="uq_org_membership_tenant_user_unit"
        ),
        Index("ix_org_memberships_tenant_user", "tenant_id", "user_id"),
    )


class Offering(Base):
    """Catalog offerings — pointer to capability/workflow (Task 45 / alembic 019)."""

    __tablename__ = "offerings"
    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="*", index=True)
    dept = Column(String(64), nullable=False, default="content_growth", index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String(32), nullable=False, default="placeholder")
    # implemented | placeholder | unimplemented
    target_kind = Column(String(32), nullable=False, default="capability")
    # capability | workflow | agent
    target_id = Column(String(128), nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)
    meta = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ContentArtifact(Base):
    """Hotspot / script outputs for content library (Task 45 / 45b).

    kind:
      - hotspot_day — 租户当日合集（归一化去重）
      - hotspot_run — 单次抓取记录（同 content_hash 幂等）
      - hotspot — 旧版单次抓取（兼容展示）
      - script — 口播稿
    """

    __tablename__ = "content_artifacts"
    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    kind = Column(String(32), nullable=False, default="hotspot")
    title = Column(String(255), nullable=False, default="")
    body = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=True)
    run_id = Column(String(36), nullable=True)
    creator_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("ix_content_artifacts_tenant_kind_created", "tenant_id", "kind", "created_at"),
    )


class SocialAccount(Base):
    """Global platform account cache (Task 52) — no tenant_id."""

    __tablename__ = "social_accounts"
    id = Column(_PK, primary_key=True, autoincrement=True)
    platform = Column(Text, nullable=False)
    account_key = Column(Text, nullable=False)
    external_id = Column(Text, nullable=True)
    nickname = Column(Text, nullable=True)
    avatar_url = Column(Text, nullable=True)
    follower_count = Column(BigInteger, nullable=True)
    total_favorited = Column(BigInteger, nullable=True)
    content_count = Column(BigInteger, nullable=True)
    last_fetched_at = Column(DateTime(timezone=True), nullable=True)
    extra_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("platform", "account_key", name="uq_social_accounts_platform_key"),
    )


class SocialFollow(Base):
    """Tenant follow list for social accounts (Task 52). Accounts stay global."""

    __tablename__ = "social_follows"
    id = Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = Column(Text, nullable=False)
    account_id = Column(_PK, ForeignKey("social_accounts.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("tenant_id", "account_id", name="uq_social_follows_tenant_account"),
        Index("ix_social_follows_tenant", "tenant_id"),
    )


class SocialContent(Base):
    """Global content cache (Task 52)."""

    __tablename__ = "social_contents"
    id = Column(_PK, primary_key=True, autoincrement=True)
    platform = Column(Text, nullable=False)
    account_id = Column(_PK, ForeignKey("social_accounts.id"), nullable=False)
    external_id = Column(Text, nullable=False)
    content_type = Column(Text, nullable=False, default="video")
    title = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    content_source = Column(Text, nullable=False, default="desc")
    duration_s = Column(Integer, nullable=True)
    like_count = Column(Integer, nullable=True)
    comment_count = Column(Integer, nullable=True)
    share_count = Column(Integer, nullable=True)
    collect_count = Column(Integer, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    fetched_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    raw_json = Column(JSON, nullable=True)
    __table_args__ = (
        UniqueConstraint(
            "platform", "external_id", name="uq_social_contents_platform_external"
        ),
        Index("ix_social_contents_account_id", "account_id"),
    )


class SocialTask(Base):
    """Tenant analysis task queue row (Task 52) — SKIP LOCKED claim target."""

    __tablename__ = "social_tasks"
    id = Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    platform = Column(Text, nullable=False)
    account_id = Column(_PK, ForeignKey("social_accounts.id"), nullable=False)
    status = Column(Text, nullable=False, default="pending")
    progress = Column(Integer, nullable=False, default=0)
    total_count = Column(Integer, nullable=False, default=0)
    new_count = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    leased_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("ix_social_tasks_tenant_user", "tenant_id", "user_id"),
        Index("ix_social_tasks_status", "status"),
    )


class SocialTemplate(Base):
    """Tenant-scoped script templates (Task 52)."""

    __tablename__ = "social_templates"
    id = Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = Column(Text, nullable=False)
    platform = Column(Text, nullable=False)
    template_key = Column(Text, nullable=False)
    template_type = Column(Text, nullable=True)
    structure_json = Column(JSON, nullable=True)
    sample_count = Column(Integer, nullable=False, default=1)
    usage_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "platform",
            "template_key",
            name="uq_social_templates_tenant_platform_key",
        ),
        Index("ix_social_templates_tenant_platform", "tenant_id", "platform"),
    )


class SocialResult(Base):
    """Per-task analysis / replica output (Task 52)."""

    __tablename__ = "social_results"
    id = Column(_PK, primary_key=True, autoincrement=True)
    task_id = Column(_PK, ForeignKey("social_tasks.id"), nullable=False)
    content_id = Column(_PK, ForeignKey("social_contents.id"), nullable=False)
    template_id = Column(_PK, ForeignKey("social_templates.id"), nullable=True)
    structure_json = Column(JSON, nullable=True)
    replica_json = Column(JSON, nullable=True)
    __table_args__ = (
        UniqueConstraint("task_id", "content_id", name="uq_social_results_task_content"),
        Index("ix_social_results_task_id", "task_id"),
    )


class SocialUsage(Base):
    """Developer cost ledger (Task 52) — not exposed as public API."""

    __tablename__ = "social_usage"
    id = Column(_PK, primary_key=True, autoincrement=True)
    tenant_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    platform = Column(Text, nullable=True)
    operation = Column(Text, nullable=False)
    item_count = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Numeric(10, 4), nullable=True)
    price_usd = Column(Numeric(10, 4), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (Index("ix_social_usage_created_at", "created_at"),)


class PGVectorSession:
    """pgvector 数据库会话管理器"""

    def __init__(self, db_url: str | None = None):
        if db_url is None:
            from backend.database.models import _resolve_database_url

            db_url = _resolve_database_url()
        self.engine = create_engine(db_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)

    def init_db(self):
        """创建所有表（仅首次部署使用）并种子角色"""
        Base.metadata.create_all(self.engine)
        self._seed_roles()

    def _seed_roles(self) -> None:
        """幂等写入默认角色"""
        from backend.core.auth.models import ROLES

        with self.Session() as session:
            for name, meta in ROLES.items():
                existing = session.query(Role).filter_by(name=name).first()
                if existing:
                    continue
                session.add(
                    Role(
                        name=name,
                        permissions=list(meta.get("permissions", [])),
                        description=str(meta.get("description", "")),
                    )
                )
            session.commit()

    @contextmanager
    def get_session(self):
        """上下文管理器获取 session"""
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def query_with_tenant(
        self,
        model_class,
        tenant_id: str,
        user_id: str | None = None,
    ):
        """带租户隔离的查询 — 自动加 WHERE tenant_id=:tid（可选 user_id）"""
        with self.Session() as session:
            q = session.query(model_class).filter(model_class.tenant_id == tenant_id)
            if user_id and hasattr(model_class, "user_id"):
                q = q.filter(model_class.user_id == user_id)
            rows = q.all()
            session.expunge_all()
            return rows

    def search_similar(
        self,
        tenant_id: str,
        embedding: list[float],
        limit: int = 5,
        min_score: float = 0.7,
    ) -> list[ChatMessage]:
        """ANN 检索相似消息"""
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        with self.Session() as session:
            sql = text(
                """
                SELECT id, tenant_id, session_id, user_id, role, content, created_at,
                       1 - (embedding <=> :vec::vector) AS similarity
                FROM chat_messages
                WHERE tenant_id = :tid
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> :vec::vector) >= :min_score
                ORDER BY embedding <=> :vec::vector
                LIMIT :lim
                """
            )
            rows = session.execute(
                sql,
                {
                    "vec": vec_str,
                    "tid": tenant_id,
                    "min_score": min_score,
                    "lim": limit,
                },
            ).fetchall()
            return [
                ChatMessage(
                    id=r.id,
                    tenant_id=r.tenant_id,
                    session_id=r.session_id,
                    user_id=r.user_id,
                    role=r.role,
                    content=r.content,
                    created_at=r.created_at,
                )
                for r in rows
            ]


_pg_session: PGVectorSession | None = None


def get_pg_session() -> PGVectorSession:
    global _pg_session
    if _pg_session is None:
        _pg_session = PGVectorSession()
    return _pg_session
