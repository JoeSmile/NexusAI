#!/usr/bin/env python3
"""上下文服务层 — 遗留 API 兼容；记忆检索经 UnifiedMemoryService。"""

from __future__ import annotations

from typing import Any

from backend.core.memory_service import get_unified_memory_service


class UserProfile(dict):
    """轻量用户画像（dict 兼容）"""

    @property
    def user_id(self) -> str:
        return str(self.get("user_id", ""))

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


class ContextService:
    """上下文服务 — 管理对话上下文（遗留 API 兼容）"""

    def __init__(
        self,
        tenant_id: str = "default",
        enable_rot_solver: bool = True,
        rot_threshold: int = 128000,
        **_kwargs: Any,
    ):
        # memory_service= 历史 kwargs 忽略，统一走 Unified
        self.tenant_id = tenant_id
        self.enable_rot_solver = enable_rot_solver
        self.rot_threshold = rot_threshold
        self._profiles: dict[str, UserProfile] = {}

    async def build_context(
        self,
        user_id: str,
        session_id: str,
        current_message: str,
        auto_reduce: bool = True,
    ) -> dict[str, Any]:
        _ = auto_reduce
        mem = get_unified_memory_service(self.tenant_id)
        memories = await mem.search_warm(
            user_id, current_message, limit=5
        )
        return {
            "user_id": user_id,
            "session_id": session_id,
            "current_message": current_message,
            "memories": memories,
        }

    async def build_prompt(self, context: dict[str, Any]) -> str:
        parts = [f"User: {context.get('current_message', '')}"]
        for m in context.get("memories") or []:
            parts.append(f"Memory: {m.get('content', '')}")
        return "\n".join(parts)

    async def get_user_profile(self, user_id: str) -> UserProfile:
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile(user_id=user_id)
        return self._profiles[user_id]

    async def update_user_profile(
        self, user_id: str, updates: dict[str, Any]
    ) -> UserProfile:
        profile = await self.get_user_profile(user_id)
        profile.update(updates)
        profile["user_id"] = user_id
        return profile

    async def get_context_summary(self, context: dict[str, Any]) -> str:
        return f"memories={len(context.get('memories') or [])}"

    def get_context_status(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "tokens_est": len(str(context)) // 4}

    async def offload_context(self, context: dict[str, Any], path: str) -> str:
        return path
