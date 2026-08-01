"""Initial schema — ContextGate 全量表结构

Revision ID: 001
Revises: 
Create Date: 2026-08-01

说明:
- 由两套 ORM Base(legacy + pgvector)合并生成,覆盖全部 24 张表
- 已移除旧版遗留:emotion_analysis / feedbacks / system_events /
  user_languages 等孤儿表,以及 chat_messages.emotion、memory_items.emotion、
  response_evaluations.user_emotion 等情绪字段
- roles 表种子数据与 backend/core/auth/models.py ROLES 保持一致(增删需同步)
"""

import json

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None

# 默认角色种子 — 与 backend/core/auth/models.py ROLES 保持一致
_DEFAULT_ROLES = [
    {
        "name": "super_admin",
        "permissions": ["admin:*", "audit:read", "audit:export"],
        "description": "跨租户管理员",
    },
    {
        "name": "auditor",
        "permissions": ["audit:read", "audit:export"],
        "description": "跨租户审计员",
    },
    {
        "name": "tenant_admin",
        "permissions": ["chat:*", "kb:*", "admin:approve", "admin:llm_key"],
        "description": "租户管理员",
    },
    {
        "name": "user",
        "permissions": ["chat:write", "chat:read"],
        "description": "普通用户",
    },
]


def upgrade() -> None:
    # ── 用户与认证 ──────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_user_id"), "users", ["user_id"], unique=True)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=8), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("access_key_id", sa.String(length=64), nullable=True),
        sa.Column("access_key_secret", sa.Text(), nullable=True),
        sa.Column("signature_enabled", sa.Boolean(), nullable=True),
        sa.Column("signature_key_version", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_key_id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index(op.f("ix_api_keys_tenant_id"), "api_keys", ["tenant_id"], unique=False)

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "user_app_perms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id"),
    )

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("resource", sa.String(length=256), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("timeout_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_apr_tenant_status", "approval_requests", ["tenant_id", "status"], unique=False
    )

    op.create_table(
        "llm_api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("key_alias", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=256), nullable=True),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_verified", sa.DateTime(), nullable=True),
        sa.Column("last_verified_ok", sa.Boolean(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("rotated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key_alias"),
    )
    op.create_index(
        "idx_lak_tenant", "llm_api_keys", ["tenant_id", "is_active"], unique=False
    )

    # ── 会话与消息 ──────────────────────────────────────────────
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_sessions_session_id"), "chat_sessions", ["session_id"], unique=True)
    op.create_index(op.f("ix_chat_sessions_tenant_id"), "chat_sessions", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_messages_tenant_session", "chat_messages", ["tenant_id", "session_id"], unique=False
    )
    op.create_index(op.f("ix_chat_messages_session_id"), "chat_messages", ["session_id"], unique=False)
    op.create_index(op.f("ix_chat_messages_tenant_id"), "chat_messages", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_chat_messages_user_id"), "chat_messages", ["user_id"], unique=False)

    # ── 记忆 ────────────────────────────────────────────────────
    op.create_table(
        "user_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "key"),
    )
    op.create_index(op.f("ix_user_memories_tenant_id"), "user_memories", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_user_memories_user_id"), "user_memories", ["user_id"], unique=False)

    op.create_table(
        "cold_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cold_memories_tenant_id"), "cold_memories", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_cold_memories_user_id"), "cold_memories", ["user_id"], unique=False)

    op.create_table(
        "memory_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.String(length=100), nullable=True),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("memory_type", sa.String(length=50), nullable=True),
        sa.Column("importance", sa.Float(), nullable=True),
        sa.Column("extraction_method", sa.String(length=50), nullable=True),
        sa.Column("keywords", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=True),
        sa.Column("last_accessed", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_memory_items_id"), "memory_items", ["id"], unique=False)
    op.create_index(op.f("ix_memory_items_memory_id"), "memory_items", ["memory_id"], unique=True)
    op.create_index(op.f("ix_memory_items_session_id"), "memory_items", ["session_id"], unique=False)
    op.create_index(op.f("ix_memory_items_user_id"), "memory_items", ["user_id"], unique=False)

    # ── 知识 ────────────────────────────────────────────────────
    op.create_table(
        "knowledge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_id"), "knowledge", ["id"], unique=False)

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=256), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_chunks_category"), "knowledge_chunks", ["category"], unique=False)
    op.create_index(op.f("ix_knowledge_chunks_tenant_id"), "knowledge_chunks", ["tenant_id"], unique=False)

    # ── 评估与反馈 ──────────────────────────────────────────────
    op.create_table(
        "response_evaluations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=True),
        sa.Column("bot_response", sa.Text(), nullable=True),
        sa.Column("accuracy_score", sa.Float(), nullable=True),
        sa.Column("naturalness_score", sa.Float(), nullable=True),
        sa.Column("safety_score", sa.Float(), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("average_score", sa.Float(), nullable=True),
        sa.Column("accuracy_reasoning", sa.Text(), nullable=True),
        sa.Column("naturalness_reasoning", sa.Text(), nullable=True),
        sa.Column("safety_reasoning", sa.Text(), nullable=True),
        sa.Column("overall_comment", sa.Text(), nullable=True),
        sa.Column("strengths", sa.Text(), nullable=True),
        sa.Column("weaknesses", sa.Text(), nullable=True),
        sa.Column("improvement_suggestions", sa.Text(), nullable=True),
        sa.Column("evaluation_model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("is_human_verified", sa.Boolean(), nullable=True),
        sa.Column("human_rating_diff", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_response_evaluations_id"), "response_evaluations", ["id"], unique=False)
    op.create_index(
        op.f("ix_response_evaluations_message_id"), "response_evaluations", ["message_id"], unique=False
    )
    op.create_index(
        op.f("ix_response_evaluations_session_id"), "response_evaluations", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_response_evaluations_user_id"), "response_evaluations", ["user_id"], unique=False
    )

    op.create_table(
        "user_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("feedback_type", sa.String(length=50), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=True),
        sa.Column("bot_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("is_resolved", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_feedback_id"), "user_feedback", ["id"], unique=False)
    op.create_index(op.f("ix_user_feedback_message_id"), "user_feedback", ["message_id"], unique=False)
    op.create_index(op.f("ix_user_feedback_session_id"), "user_feedback", ["session_id"], unique=False)
    op.create_index(op.f("ix_user_feedback_user_id"), "user_feedback", ["user_id"], unique=False)

    # ── 用户画像与个性化 ────────────────────────────────────────
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("gender", sa.String(length=20), nullable=True),
        sa.Column("personality_traits", sa.Text(), nullable=True),
        sa.Column("interests", sa.Text(), nullable=True),
        sa.Column("concerns", sa.Text(), nullable=True),
        sa.Column("communication_style", sa.String(length=50), nullable=True),
        sa.Column("total_sessions", sa.Integer(), nullable=True),
        sa.Column("total_messages", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_profiles_id"), "user_profiles", ["id"], unique=False)
    op.create_index(op.f("ix_user_profiles_user_id"), "user_profiles", ["user_id"], unique=True)

    op.create_table(
        "user_personalizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("role_name", sa.String(length=100), nullable=True),
        sa.Column("role_background", sa.Text(), nullable=True),
        sa.Column("personality", sa.String(length=100), nullable=True),
        sa.Column("core_principles", sa.Text(), nullable=True),
        sa.Column("forbidden_behaviors", sa.Text(), nullable=True),
        sa.Column("tone", sa.String(length=50), nullable=True),
        sa.Column("style", sa.String(length=50), nullable=True),
        sa.Column("formality", sa.Float(), nullable=True),
        sa.Column("enthusiasm", sa.Float(), nullable=True),
        sa.Column("humor_level", sa.Float(), nullable=True),
        sa.Column("response_length", sa.String(length=20), nullable=True),
        sa.Column("use_emoji", sa.Boolean(), nullable=True),
        sa.Column("preferred_topics", sa.Text(), nullable=True),
        sa.Column("avoided_topics", sa.Text(), nullable=True),
        sa.Column("communication_preferences", sa.Text(), nullable=True),
        sa.Column("learning_mode", sa.Boolean(), nullable=True),
        sa.Column("safety_level", sa.String(length=20), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("situational_roles", sa.Text(), nullable=True),
        sa.Column("active_role", sa.String(length=50), nullable=True),
        sa.Column("total_interactions", sa.Integer(), nullable=True),
        sa.Column("positive_feedbacks", sa.Integer(), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_personalizations_id"), "user_personalizations", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_user_personalizations_user_id"), "user_personalizations", ["user_id"], unique=True
    )

    # ── A/B 测试 ────────────────────────────────────────────────
    op.create_table(
        "ab_test_experiments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("groups", sa.Text(), nullable=True),
        sa.Column("weights", sa.Text(), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("extra_metadata", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ab_test_experiments_experiment_id"),
        "ab_test_experiments",
        ["experiment_id"],
        unique=True,
    )
    op.create_index(op.f("ix_ab_test_experiments_id"), "ab_test_experiments", ["id"], unique=False)

    op.create_table(
        "ab_test_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("experiment_id", sa.String(length=100), nullable=True),
        sa.Column("group", sa.String(length=50), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=True),
        sa.Column("event_data", sa.Text(), nullable=True),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ab_test_events_event_type"), "ab_test_events", ["event_type"], unique=False)
    op.create_index(
        op.f("ix_ab_test_events_experiment_id"), "ab_test_events", ["experiment_id"], unique=False
    )
    op.create_index(op.f("ix_ab_test_events_group"), "ab_test_events", ["group"], unique=False)
    op.create_index(op.f("ix_ab_test_events_id"), "ab_test_events", ["id"], unique=False)
    op.create_index(op.f("ix_ab_test_events_session_id"), "ab_test_events", ["session_id"], unique=False)
    op.create_index(op.f("ix_ab_test_events_timestamp"), "ab_test_events", ["timestamp"], unique=False)
    op.create_index(op.f("ix_ab_test_events_user_id"), "ab_test_events", ["user_id"], unique=False)

    op.create_table(
        "ab_test_group_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("experiment_id", sa.String(length=100), nullable=True),
        sa.Column("group", sa.String(length=50), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ab_test_group_assignments_experiment_id"),
        "ab_test_group_assignments",
        ["experiment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ab_test_group_assignments_group"), "ab_test_group_assignments", ["group"], unique=False
    )
    op.create_index(
        op.f("ix_ab_test_group_assignments_id"), "ab_test_group_assignments", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_ab_test_group_assignments_user_id"),
        "ab_test_group_assignments",
        ["user_id"],
        unique=False,
    )

    # ── 系统与审计 ──────────────────────────────────────────────
    op.create_table(
        "system_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("user_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_logs_id"), "system_logs", ["id"], unique=False)
    op.create_index(op.f("ix_system_logs_session_id"), "system_logs", ["session_id"], unique=False)
    op.create_index(op.f("ix_system_logs_user_id"), "system_logs", ["user_id"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("trace_id", sa.String(length=100), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("ip_address", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_tenant_time", "audit_logs", ["tenant_id", "created_at"], unique=False)
    op.create_index(op.f("ix_audit_logs_tenant_id"), "audit_logs", ["tenant_id"], unique=False)

    op.create_table(
        "cache_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cache_key", sa.String(length=256), nullable=False),
        sa.Column("cache_type", sa.String(length=20), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("ttl_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cache_entries_cache_key"), "cache_entries", ["cache_key"], unique=True)

    op.create_table(
        "tenant_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )

    # ── 种子数据:默认角色 ───────────────────────────────────────
    for role in _DEFAULT_ROLES:
        op.execute(
            sa.text(
                "INSERT INTO roles (name, permissions, description) "
                "VALUES (:name, CAST(:permissions AS JSON), :description) "
                "ON CONFLICT (name) DO NOTHING"
            ).bindparams(
                name=role["name"],
                permissions=json.dumps(role["permissions"], ensure_ascii=False),
                description=role["description"],
            )
        )


def downgrade() -> None:
    """删除所有表"""
    op.drop_table("tenant_config")
    op.drop_index(op.f("ix_cache_entries_cache_key"), table_name="cache_entries")
    op.drop_table("cache_entries")
    op.drop_index(op.f("ix_audit_logs_tenant_id"), table_name="audit_logs")
    op.drop_index("idx_audit_tenant_time", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_system_logs_user_id"), table_name="system_logs")
    op.drop_index(op.f("ix_system_logs_session_id"), table_name="system_logs")
    op.drop_index(op.f("ix_system_logs_id"), table_name="system_logs")
    op.drop_table("system_logs")
    op.drop_index(
        op.f("ix_ab_test_group_assignments_user_id"), table_name="ab_test_group_assignments"
    )
    op.drop_index(
        op.f("ix_ab_test_group_assignments_id"), table_name="ab_test_group_assignments"
    )
    op.drop_index(
        op.f("ix_ab_test_group_assignments_group"), table_name="ab_test_group_assignments"
    )
    op.drop_index(
        op.f("ix_ab_test_group_assignments_experiment_id"),
        table_name="ab_test_group_assignments",
    )
    op.drop_table("ab_test_group_assignments")
    op.drop_index(op.f("ix_ab_test_events_user_id"), table_name="ab_test_events")
    op.drop_index(op.f("ix_ab_test_events_timestamp"), table_name="ab_test_events")
    op.drop_index(op.f("ix_ab_test_events_session_id"), table_name="ab_test_events")
    op.drop_index(op.f("ix_ab_test_events_id"), table_name="ab_test_events")
    op.drop_index(op.f("ix_ab_test_events_group"), table_name="ab_test_events")
    op.drop_index(op.f("ix_ab_test_events_experiment_id"), table_name="ab_test_events")
    op.drop_index(op.f("ix_ab_test_events_event_type"), table_name="ab_test_events")
    op.drop_table("ab_test_events")
    op.drop_index(op.f("ix_ab_test_experiments_id"), table_name="ab_test_experiments")
    op.drop_index(
        op.f("ix_ab_test_experiments_experiment_id"), table_name="ab_test_experiments"
    )
    op.drop_table("ab_test_experiments")
    op.drop_index(
        op.f("ix_user_personalizations_user_id"), table_name="user_personalizations"
    )
    op.drop_index(op.f("ix_user_personalizations_id"), table_name="user_personalizations")
    op.drop_table("user_personalizations")
    op.drop_index(op.f("ix_user_profiles_user_id"), table_name="user_profiles")
    op.drop_index(op.f("ix_user_profiles_id"), table_name="user_profiles")
    op.drop_table("user_profiles")
    op.drop_index(op.f("ix_user_feedback_user_id"), table_name="user_feedback")
    op.drop_index(op.f("ix_user_feedback_session_id"), table_name="user_feedback")
    op.drop_index(op.f("ix_user_feedback_message_id"), table_name="user_feedback")
    op.drop_index(op.f("ix_user_feedback_id"), table_name="user_feedback")
    op.drop_table("user_feedback")
    op.drop_index(op.f("ix_response_evaluations_user_id"), table_name="response_evaluations")
    op.drop_index(
        op.f("ix_response_evaluations_session_id"), table_name="response_evaluations"
    )
    op.drop_index(
        op.f("ix_response_evaluations_message_id"), table_name="response_evaluations"
    )
    op.drop_index(op.f("ix_response_evaluations_id"), table_name="response_evaluations")
    op.drop_table("response_evaluations")
    op.drop_index(op.f("ix_knowledge_chunks_tenant_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_category"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_id"), table_name="knowledge")
    op.drop_table("knowledge")
    op.drop_index(op.f("ix_memory_items_user_id"), table_name="memory_items")
    op.drop_index(op.f("ix_memory_items_session_id"), table_name="memory_items")
    op.drop_index(op.f("ix_memory_items_memory_id"), table_name="memory_items")
    op.drop_index(op.f("ix_memory_items_id"), table_name="memory_items")
    op.drop_table("memory_items")
    op.drop_index(op.f("ix_cold_memories_user_id"), table_name="cold_memories")
    op.drop_index(op.f("ix_cold_memories_tenant_id"), table_name="cold_memories")
    op.drop_table("cold_memories")
    op.drop_index(op.f("ix_user_memories_user_id"), table_name="user_memories")
    op.drop_index(op.f("ix_user_memories_tenant_id"), table_name="user_memories")
    op.drop_table("user_memories")
    op.drop_index(op.f("ix_chat_messages_user_id"), table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_tenant_id"), table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_session_id"), table_name="chat_messages")
    op.drop_index("idx_messages_tenant_session", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(op.f("ix_chat_sessions_user_id"), table_name="chat_sessions")
    op.drop_index(op.f("ix_chat_sessions_tenant_id"), table_name="chat_sessions")
    op.drop_index(op.f("ix_chat_sessions_session_id"), table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_index("idx_lak_tenant", table_name="llm_api_keys")
    op.drop_table("llm_api_keys")
    op.drop_index("idx_apr_tenant_status", table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_table("user_app_perms")
    op.drop_table("roles")
    op.drop_index(op.f("ix_api_keys_tenant_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index(op.f("ix_users_user_id"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
