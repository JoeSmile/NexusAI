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
            ("user", "最近项目压力好大，每天都加班到很晚", "焦虑", 8),
            (
                "assistant",
                "听起来你最近工作压力很大。能具体说说是什么样的项目吗？有时候说出来会好一些。",
                "共情",
                7,
            ),
            (
                "user",
                "公司在做一个新的AI平台，我是后端负责人，deadline特别紧",
                "焦虑",
                7,
            ),
            (
                "assistant",
                "作为后端负责人确实压力不小。你有跟团队或者上级沟通过进度的压力吗？",
                "关心",
                6,
            ),
            ("user", "说了也没用，老板就是催。我感觉快撑不住了", "无助", 9),
            (
                "assistant",
                "这种感觉确实很难受。不过请记住，你的健康比任何项目都重要。要不要试试把大任务拆成小块？",
                "建议",
                5,
            ),
        ],
    },
    {
        "session_id": "sess_bob_001",
        "user_id": "bob",
        "tenant_id": "beta",
        "messages": [
            ("user", "今天面试被拒了，心情很低落", "悲伤", 7),
            (
                "assistant",
                "被拒绝确实让人沮丧。不过每次面试都是一次学习经验，能说说是什么岗位吗？",
                "共情",
                6,
            ),
            ("user", "是一个大厂的前端岗位，准备了好久还是没过", "悲伤", 8),
            (
                "assistant",
                "大厂的竞争确实激烈。能走到面试这一步已经很厉害了。要不要我帮你梳理一下面试中的亮点？",
                "鼓励",
                5,
            ),
        ],
    },
    {
        "session_id": "sess_alice_002",
        "user_id": "alice",
        "tenant_id": "acme",
        "messages": [
            ("user", "今天跟朋友出去玩了，心情好了很多", "高兴", 7),
            (
                "assistant",
                "真为你高兴！适当的社交和放松确实能帮助缓解压力。",
                "开心",
                5,
            ),
        ],
    },
    {
        "session_id": "sess_bob_002",
        "user_id": "bob",
        "tenant_id": "beta",
        "messages": [
            ("user", "我该怎样提高自己的技术水平？", "中性", 5),
            (
                "assistant",
                "这是个很好的问题。建议你可以从这几个方面入手：1) 选择一个方向深耕 2) 多做开源项目 3) 定期复盘总结",
                "建议",
                5,
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
            for i, (role, content, emotion, intensity) in enumerate(chat["messages"]):
                session.add(
                    ChatMessage(
                        tenant_id=tid,
                        session_id=sid,
                        user_id=uid,
                        role=role,
                        content=content,
                        emotion=emotion,
                        emotion_intensity=intensity,
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


def main() -> None:
    print("=" * 60)
    print("  ContextGate — Seed pgvector Data")
    print("=" * 60)
    seed_data()
    print("=" * 60)
    print("  ✅ 数据写入完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
