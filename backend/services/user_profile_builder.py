#!/usr/bin/env python3
"""用户画像构建器 — 画像落 ``user_memories``（Task 34.01，停用 user_profiles / memory_items）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from backend.database.pgvector_session import (
    ChatMessage,
    UserMemory,
    get_pg_session,
)
from backend.database.vector_ops import store_user_memory

_PROFILE_KEY = "profile:v1"
_DEFAULT_TENANT = "default"


class ConversationGraph:
    """对话脉络图谱 - 记录关键事件之间的因果关系"""

    def __init__(self) -> None:
        self.nodes: dict[str, Any] = {}
        self.edges: list[tuple[str, str, str]] = []

    def add_node(self, node_id: str, node_type: str, content: str, timestamp: str) -> None:
        self.nodes[node_id] = {
            "type": node_type,
            "content": content,
            "timestamp": timestamp,
        }

    def add_edge(self, from_id: str, to_id: str, relation_type: str) -> None:
        self.edges.append((from_id, to_id, relation_type))

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": self.nodes, "edges": self.edges}


class UserProfileBuilder:
    """用户画像构建器 — 动态构建；持久化到 user_memories。"""

    def __init__(self, tenant_id: str = _DEFAULT_TENANT) -> None:
        self.tenant_id = tenant_id

    async def build_profile(
        self, user_id: str, force_rebuild: bool = False
    ) -> dict[str, Any]:
        try:
            session_factory = get_pg_session()
            with session_factory.Session() as session:
                row = (
                    session.query(UserMemory)
                    .filter_by(
                        tenant_id=self.tenant_id,
                        user_id=user_id,
                        key=_PROFILE_KEY,
                    )
                    .first()
                )
                if row and not force_rebuild and row.updated_at:
                    age = (datetime.utcnow() - row.updated_at).total_seconds()
                    if age < 86400:
                        return self._profile_value_to_dict(user_id, row.value)

            profile_data = await self._analyze_user_data(user_id)
            payload = {
                "user_id": user_id,
                "core_concerns": profile_data.get("core_concerns", []),
                "communication_style": profile_data.get(
                    "communication_style", "默认"
                ),
                "total_sessions": profile_data.get("total_sessions", 0),
                "total_messages": profile_data.get("total_messages", 0),
                "updated_at": datetime.utcnow().isoformat(),
            }
            store_user_memory(
                tenant_id=self.tenant_id,
                user_id=user_id,
                key=_PROFILE_KEY,
                value=json.dumps(payload, ensure_ascii=False),
                confidence=0.8,
                source="profile",
            )
            return payload
        except Exception as e:
            print(f"构建用户画像失败: {e}")
            import traceback

            traceback.print_exc()
            return self._get_default_profile(user_id)

    async def _analyze_user_data(self, user_id: str) -> dict[str, Any]:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            messages = (
                session.query(ChatMessage)
                .filter(
                    ChatMessage.tenant_id == self.tenant_id,
                    ChatMessage.user_id == user_id,
                    ChatMessage.role == "user",
                    ChatMessage.created_at >= cutoff_date,
                )
                .all()
            )
            memories = (
                session.query(UserMemory)
                .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                .filter(UserMemory.key != _PROFILE_KEY)
                .all()
            )
            total_sessions = (
                session.query(func.count(func.distinct(ChatMessage.session_id)))
                .filter(
                    ChatMessage.tenant_id == self.tenant_id,
                    ChatMessage.user_id == user_id,
                )
                .scalar()
                or 0
            )

        core_concerns = self._extract_core_concerns(memories)
        communication_style = self._analyze_communication_style(messages)
        important_events = self._extract_important_events(memories)

        return {
            "core_concerns": core_concerns,
            "communication_style": communication_style,
            "important_events": important_events,
            "total_sessions": total_sessions,
            "total_messages": len(messages),
        }

    def _extract_core_concerns(self, memories: list[UserMemory]) -> list[str]:
        concerns: list[str] = []
        for memory in memories:
            src = (memory.source or "").lower()
            key = (memory.key or "").lower()
            if "concern" in src or key.startswith("concern"):
                concerns.append((memory.value or "")[:50])
        return concerns[:5]

    def _analyze_communication_style(self, messages: list[ChatMessage]) -> str:
        if not messages:
            return "默认"
        avg_length = sum(len(m.content or "") for m in messages) / len(messages)
        question_count = sum(
            1
            for m in messages
            if m.content
            and ("?" in m.content or "吗" in m.content or "呢" in m.content)
        )
        question_ratio = question_count / len(messages)
        if avg_length > 100:
            length_style = "详细表达型"
        elif avg_length > 50:
            length_style = "适度表达型"
        else:
            length_style = "简洁表达型"
        interaction_style = "主动提问型" if question_ratio > 0.5 else "理性交流型"
        return f"{length_style}，{interaction_style}"

    def _extract_important_events(
        self, memories: list[UserMemory]
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for memory in memories:
            src = (memory.source or "").lower()
            key = (memory.key or "").lower()
            importance = float(memory.confidence or 0)
            if ("event" in src or key.startswith("event")) and importance > 0.6:
                events.append(
                    {
                        "date": (
                            memory.created_at.strftime("%Y-%m-%d")
                            if memory.created_at
                            else ""
                        ),
                        "event": (memory.value or "")[:50],
                        "importance": importance,
                    }
                )
        events.sort(key=lambda x: x["importance"], reverse=True)
        return events[:5]

    def _profile_value_to_dict(self, user_id: str, value: str | None) -> dict[str, Any]:
        try:
            data = json.loads(value) if value else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("user_id", user_id)
        data.setdefault("core_concerns", [])
        data.setdefault("communication_style", "默认")
        data.setdefault("total_sessions", 0)
        data.setdefault("total_messages", 0)
        return data

    def _get_default_profile(self, user_id: str) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "core_concerns": [],
            "communication_style": "默认",
            "total_sessions": 0,
            "total_messages": 0,
            "updated_at": None,
        }

    async def build_conversation_graph(self, user_id: str) -> dict[str, Any]:
        try:
            session_factory = get_pg_session()
            with session_factory.Session() as session:
                memories = (
                    session.query(UserMemory)
                    .filter_by(tenant_id=self.tenant_id, user_id=user_id)
                    .filter(UserMemory.key != _PROFILE_KEY)
                    .filter(UserMemory.confidence > 0.6)
                    .order_by(UserMemory.created_at)
                    .all()
                )
            graph = ConversationGraph()
            for memory in memories:
                mid = str(memory.id)
                mtype = memory.source or "other"
                graph.add_node(
                    node_id=mid,
                    node_type=mtype,
                    content=(memory.value or "")[:50],
                    timestamp=(
                        memory.created_at.isoformat() if memory.created_at else ""
                    ),
                )
            for i, current in enumerate(memories[:-1]):
                nxt = memories[i + 1]
                ct = (current.source or "").lower()
                nt = (nxt.source or "").lower()
                if "concern" in ct and "event" in nt:
                    graph.add_edge(str(current.id), str(nxt.id), "导致")
                elif "event" in ct and "concern" in nt:
                    graph.add_edge(str(current.id), str(nxt.id), "加剧")
                elif "event" in ct and "relationship" in nt:
                    graph.add_edge(str(current.id), str(nxt.id), "影响")
            return graph.to_dict()
        except Exception as e:
            print(f"构建对话图谱失败: {e}")
            return {"nodes": {}, "edges": []}

    async def generate_profile_summary(self, user_id: str) -> str:
        profile = await self.build_profile(user_id)
        summary_parts: list[str] = []
        if profile.get("core_concerns"):
            concerns_str = "、".join(profile["core_concerns"][:3])
            summary_parts.append(f"核心关注：{concerns_str}")
        if profile.get("communication_style"):
            summary_parts.append(f"沟通风格：{profile['communication_style']}")
        if profile.get("total_messages", 0) > 0:
            summary_parts.append(f"已互动{profile['total_messages']}次")
        if not summary_parts:
            return "新用户，尚无画像数据"
        return "；".join(summary_parts)
