-- pgvector 初始化脚本
-- 替换 MySQL + ChromaDB，一张 PostgreSQL 搞定关系和向量存储

CREATE EXTENSION IF NOT EXISTS vector;

-- ========== 会话表 ==========
CREATE TABLE IF NOT EXISTS chat_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(100) UNIQUE NOT NULL,
    user_id         VARCHAR(100) NOT NULL DEFAULT 'anonymous',
    title           TEXT,
    status          VARCHAR(20) DEFAULT 'active',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user_id);

-- ========== 消息表（含 embedding 列，彻底替代 ChromaDB）==========
CREATE TABLE IF NOT EXISTS chat_messages (
    id                SERIAL PRIMARY KEY,
    session_id        VARCHAR(100) NOT NULL REFERENCES chat_sessions(session_id),
    user_id           VARCHAR(100) NOT NULL DEFAULT 'anonymous',
    role              VARCHAR(20) NOT NULL,  -- 'user' | 'assistant' | 'system'
    content           TEXT NOT NULL,
    emotion           VARCHAR(50),
    emotion_intensity REAL DEFAULT 5.0,
    embedding         VECTOR(1536),          -- 语义向量，用于 ANN 检索
    created_at        TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON chat_messages(created_at DESC);
-- IVFFlat 索引加速 ANN 查询
CREATE INDEX IF NOT EXISTS idx_messages_embedding ON chat_messages
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ========== 记忆表（L2 温记忆 — 用户画像键值对）==========
CREATE TABLE IF NOT EXISTS user_memories (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(100) NOT NULL,
    key             VARCHAR(200) NOT NULL,     -- 如 'preferred_city', 'occupation', 'personality_trait'
    value           TEXT NOT NULL,
    confidence      REAL DEFAULT 1.0,          -- 置信度
    source          VARCHAR(50) DEFAULT 'extracted',  -- 'extracted' | 'manual' | 'inferred'
    embedding       VECTOR(1536),              -- 语义版本（用于跨会话检索）
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, key)
);
CREATE INDEX IF NOT EXISTS idx_memories_user ON user_memories(user_id);

-- ========== 冷记忆表（L3 — 会话摘要向量）==========
CREATE TABLE IF NOT EXISTS cold_memories (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(100) NOT NULL,
    session_id      VARCHAR(100),
    summary         TEXT NOT NULL,              -- 小模型压缩后的摘要
    emotion_tags    TEXT[],                     -- 情绪标签数组
    start_at        TIMESTAMP,
    end_at          TIMESTAMP,
    embedding       VECTOR(1536),
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cold_user ON cold_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_cold_embedding ON cold_memories
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- ========== 反馈表 ==========
CREATE TABLE IF NOT EXISTS feedbacks (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(100) NOT NULL,
    user_id         VARCHAR(100) DEFAULT 'anonymous',
    message_id      INTEGER,
    feedback_type   VARCHAR(20) NOT NULL,       -- 'like' | 'dislike' | 'report'
    rating          INTEGER DEFAULT 0,
    comment         TEXT DEFAULT '',
    user_message    TEXT DEFAULT '',
    bot_response    TEXT DEFAULT '',
    is_resolved     BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ========== 自动评估表 ==========
CREATE TABLE IF NOT EXISTS response_evaluations (
    id                      SERIAL PRIMARY KEY,
    session_id              VARCHAR(100),
    user_id                 VARCHAR(100),
    message_id              INTEGER,
    user_message            TEXT,
    bot_response            TEXT,
    user_emotion            VARCHAR(50),
    emotion_intensity       REAL,
    empathy_score           REAL,
    naturalness_score       REAL,
    safety_score            REAL,
    total_score             REAL,
    average_score           REAL,
    overall_comment         TEXT,
    model                   VARCHAR(100),
    prompt_version          VARCHAR(50),
    created_at              TIMESTAMP DEFAULT NOW()
);

-- ========== 语言切换偏好 ==========
CREATE TABLE IF NOT EXISTS user_languages (
    id              SERIAL PRIMARY KEY,
    user_id         VARCHAR(100) NOT NULL,
    language        VARCHAR(10) NOT NULL DEFAULT 'zh',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id)
);

-- ========== 系统事件日志（替代老的 SystemLog 表）==========
CREATE TABLE IF NOT EXISTS system_events (
    id              SERIAL PRIMARY KEY,
    level           VARCHAR(20) DEFAULT 'INFO',
    message         TEXT,
    trace_id        VARCHAR(100),              -- 关联 LangFuse trace
    session_id      VARCHAR(100),
    user_id         VARCHAR(100),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_events_level ON system_events(level);
CREATE INDEX IF NOT EXISTS idx_events_created ON system_events(created_at DESC);

-- ========== 辅助函数：向量相似度搜索 ==========
CREATE OR REPLACE FUNCTION search_similar_memories(
    p_user_id VARCHAR(100),
    p_embedding VECTOR(1536),
    p_limit INTEGER DEFAULT 5,
    p_min_score REAL DEFAULT 0.7
)
RETURNS TABLE(
    id INTEGER,
    content TEXT,
    role VARCHAR(20),
    similarity REAL,
    created_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        cm.id,
        cm.content,
        cm.role,
        1 - (cm.embedding <=> p_embedding) AS similarity,
        cm.created_at
    FROM chat_messages cm
    WHERE cm.user_id = p_user_id
      AND cm.embedding IS NOT NULL
      AND 1 - (cm.embedding <=> p_embedding) >= p_min_score
    ORDER BY cm.embedding <=> p_embedding
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ========== Task 02: 权限表 ==========

-- API Keys 表
CREATE TABLE IF NOT EXISTS api_keys (
    id                  SERIAL PRIMARY KEY,
    tenant_id           VARCHAR(64) NOT NULL,
    user_id             VARCHAR(128) NOT NULL,
    key_hash            VARCHAR(64) UNIQUE NOT NULL,
    key_prefix          VARCHAR(8),
    role                VARCHAR(32) NOT NULL DEFAULT 'user',
    is_active           BOOLEAN DEFAULT true,
    expires_at          TIMESTAMPTZ,
    description         TEXT DEFAULT '',
    created_by          VARCHAR(128),
    created_at          TIMESTAMPTZ DEFAULT now(),
    access_key_id       VARCHAR(64) UNIQUE,
    access_key_secret   TEXT,
    signature_enabled   BOOLEAN DEFAULT false,
    signature_key_version INT DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_ak_tenant ON api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ak_access_key ON api_keys(access_key_id);

-- 角色表
CREATE TABLE IF NOT EXISTS roles (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(32) UNIQUE NOT NULL,
    permissions JSONB NOT NULL DEFAULT '[]',
    description TEXT DEFAULT ''
);

-- 用户应用权限（附加权限）
CREATE TABLE IF NOT EXISTS user_app_perms (
    id          SERIAL PRIMARY KEY,
    tenant_id   VARCHAR(64) NOT NULL,
    user_id     VARCHAR(128) NOT NULL,
    permissions JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, user_id)
);

-- 审批请求表（权限申请 + Skill 人工介入）
CREATE TABLE IF NOT EXISTS approval_requests (
    id            SERIAL PRIMARY KEY,
    tenant_id     VARCHAR(64) NOT NULL,
    user_id       VARCHAR(128) NOT NULL,
    resource      VARCHAR(256) NOT NULL,
    resource_type VARCHAR(32) NOT NULL DEFAULT 'permission',
    action        VARCHAR(64) NOT NULL,
    params        JSONB DEFAULT '{}',
    status        VARCHAR(16) NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ DEFAULT now(),
    timeout_at    TIMESTAMPTZ,
    reviewed_by   VARCHAR(128),
    reviewed_at   TIMESTAMPTZ,
    review_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_apr_tenant_status ON approval_requests(tenant_id, status);

-- 初始角色数据
INSERT INTO roles (name, permissions, description) VALUES
('super_admin', '["admin:*", "audit:read", "audit:export"]', '跨租户管理员'),
('auditor',     '["audit:read", "audit:export"]', '跨租户审计员'),
('tenant_admin', '["chat:*", "kb:*", "admin:approve", "admin:llm_key"]', '租户管理员'),
('user',        '["chat:write", "chat:read"]', '普通用户')
ON CONFLICT (name) DO NOTHING;

-- ========== Task 03: 审计日志 ==========
CREATE TABLE IF NOT EXISTS audit_logs (
    id              SERIAL PRIMARY KEY,
    tenant_id       VARCHAR(64) NOT NULL,
    user_id         VARCHAR(128) NOT NULL,
    action          VARCHAR(100) NOT NULL,
    trace_id        VARCHAR(100),
    input_text      TEXT,
    output_text     TEXT,
    model           VARCHAR(100) DEFAULT '',
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cost            DOUBLE PRECISION DEFAULT 0.0,
    latency_ms      DOUBLE PRECISION DEFAULT 0.0,
    error_code      VARCHAR(50),
    ip_address      VARCHAR(50) DEFAULT '',
    user_agent      TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_logs(tenant_id, created_at);
