#!/usr/bin/env python3
"""写入示例对话数据 + 记忆数据 — 开发环境使用"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from backend.database.pgvector_session import (
    ChatMessage,
    ChatSession,
    UserMemory,
    get_pg_session,
)


def _mock_embedding() -> list[float]:
    rng = np.random.RandomState(42)
    return rng.randn(1536).tolist()


SEED_CHATS = [
    {
        "session_id": "sess_alice_001",
        "user_id": "alice",
        "tenant_id": "acme",
        "messages": [
            ("user", "请帮我整理今天项目周会的会议纪要"),
            (
                "assistant",
                "已整理会议纪要：1) 确认 Q3 里程碑时间表 2) API 网关性能优化进入开发阶段 3) 下周评审数据脱敏方案。",
            ),
            (
                "user",
                "会议里提到的数据脱敏方案能再详细说明一下吗",
            ),
            (
                "assistant",
                "数据脱敏方案要点：对敏感字段（手机号、身份证、API Key）采用 AES-256 加密存储，日志输出前做 PII 识别与遮蔽，测试环境使用合成数据。",
            ),
        ],
    },
    {
        "session_id": "sess_bob_001",
        "user_id": "bob",
        "tenant_id": "beta",
        "messages": [
            ("user", "我们想评估一下 LLM 网关选型，主要看哪些维度？"),
            (
                "assistant",
                "建议从六个维度评估：1) 多租户隔离与 RBAC 2) 可观测性（全链路 trace）3) 模型路由与成本控制 4) 安全护栏（注入检测/输出审查）5) 缓存与性能 6) 审计合规能力。",
            ),
            ("user", "安全护栏这块有哪些具体能力？"),
            (
                "assistant",
                "安全护栏包括：Prompt 注入检测、PII 脱敏、输出内容审查、速率限制、断路器、异常检测与审计日志，覆盖输入到输出的全链路。",
            ),
        ],
    },
    {
        "session_id": "sess_alice_002",
        "user_id": "alice",
        "tenant_id": "acme",
        "messages": [
            ("user", "LangFuse 的 trace 数据怎么和我们自己的审计系统对接？"),
            (
                "assistant",
                "LangFuse 提供导出 API 与 webhook，可将 trace/span 数据同步到自建审计系统；生产环境建议只导出脱敏后的元数据，敏感内容保留在域内。",
            ),
        ],
    },
    {
        "session_id": "sess_bob_002",
        "user_id": "bob",
        "tenant_id": "beta",
        "messages": [
            ("user", "小模型本地部署的量化方案怎么选？"),
            (
                "assistant",
                "推荐 7B 级模型 Q4 量化（约 4GB 显存），用 vLLM 提供 OpenAI 兼容接口；32G 内存 + 16G 显存可同时跑 1-2 个量化模型，按场景注册为独立 provider key。",
            ),
        ],
    },
]


def seed_data() -> None:
    session_factory = get_pg_session()

    for chat in SEED_CHATS:
        sid = chat["session_id"]
        uid = chat["user_id"]
        tid = chat["tenant_id"]

        with session_factory.Session() as session:
            existing = session.query(ChatSession).filter_by(session_id=sid).first()
            if not existing:
                session.add(
                    ChatSession(
                        session_id=sid,
                        tenant_id=tid,
                        user_id=uid,
                        title=f"对话 {sid}",
                    )
                )
                session.commit()

        with session_factory.Session() as session:
            existing_msgs = (
                session.query(ChatMessage).filter_by(session_id=sid).count()
            )
            if existing_msgs:
                print(f"  ⏭  {sid}: 已有 {existing_msgs} 条消息，跳过")
                continue
            for i, (role, content) in enumerate(chat["messages"]):
                session.add(
                    ChatMessage(
                        tenant_id=tid,
                        session_id=sid,
                        user_id=uid,
                        role=role,
                        content=content,
                        embedding=_mock_embedding(),
                        created_at=datetime.utcnow()
                        - timedelta(minutes=len(chat["messages"]) - i),
                    )
                )
            session.commit()
        print(f"  ✅ {sid}: {len(chat['messages'])} 条消息已写入")

    with session_factory.Session() as session:
        profiles = [
            ("acme", "alice", "occupation", "后端开发工程师"),
            ("acme", "alice", "city", "北京"),
            ("acme", "alice", "personality", "认真负责，容易焦虑"),
            ("beta", "bob", "occupation", "前端开发工程师"),
            ("beta", "bob", "city", "上海"),
            ("beta", "bob", "personality", "积极向上，偶尔迷茫"),
        ]
        written = 0
        for tid, uid, key, value in profiles:
            existing = (
                session.query(UserMemory)
                .filter_by(tenant_id=tid, user_id=uid, key=key)
                .first()
            )
            if not existing:
                session.add(
                    UserMemory(
                        tenant_id=tid,
                        user_id=uid,
                        key=key,
                        value=value,
                        confidence=0.9,
                        embedding=_mock_embedding(),
                    )
                )
                written += 1
        session.commit()
        print(f"  ✅ 用户画像已写入 ({written} 条新增 / {len(profiles)} 条定义)")


def seed_llm_keys() -> None:
    """写入初始 LLM API Key（从 env 迁移到数据库）"""
    import os

    from sqlalchemy import text

    from backend.core.key_manager import KeyManager
    from backend.database.pgvector_session import get_pg_session

    env_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    if not env_key:
        print("  ⚠️  未找到 LLM_API_KEY 环境变量，跳过 seed LLM Key")
        return
    if not os.getenv("LLM_KEY_MASTER_KEY"):
        print("  ⚠️  未设置 LLM_KEY_MASTER_KEY，跳过 seed LLM Key")
        return

    km = KeyManager()
    encrypted = km.encrypt(env_key)
    base_url = os.getenv("LLM_BASE_URL") or ""

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text(
            """
            INSERT INTO llm_api_keys
                (tenant_id, key_alias, provider, base_url, encrypted_key,
                 description, created_by)
            VALUES
                ('*', 'default-env', 'deepseek', :url, :enc,
                 '从环境变量迁移的默认 Key', 'seed_script')
            ON CONFLICT (tenant_id, key_alias) DO NOTHING
            RETURNING id
            """
        )
        row = session.execute(sql, {"enc": encrypted, "url": base_url}).fetchone()
        session.commit()

    if row:
        print(f"  ✅ LLM API Key 已加密存储到数据库 (id={row.id})")
    else:
        print("  ℹ️  LLM API Key 已存在，跳过")


def main() -> None:
    print("=" * 60)
    print("  ContextGate — Seed pgvector Data")
    print("=" * 60)
    seed_data()
    seed_llm_keys()
    print("=" * 60)
    print("  ✅ 数据写入完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
