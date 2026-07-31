"""Skill 基类 — 安全壳（二级权限 + 人工介入）"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import text

from backend.database.pgvector_session import get_pg_session


@dataclass
class SkillResult:
    """Skill 执行结果"""

    output: str
    latency_ms: float = 0.0
    success: bool = True
    error: str | None = None
    approval_request_id: str | None = None


class BaseSkill(ABC):
    """Skill 基类 — 安全壳 + 实际执行"""

    id: str = ""
    name: str = ""
    description: str = ""
    trigger_intents: list[str] = []
    tool_schema: dict = {}
    required_permissions: list[str] = []
    requires_human_approval: bool = False
    approval_timeout: int = 3600

    async def execute(
        self,
        entities: dict,
        tenant_id: str,
        user_context: dict | None = None,
    ) -> SkillResult:
        """安全壳 + 实际执行"""
        perms = user_context.get("permissions", []) if user_context else []

        if self.required_permissions:
            for perm in self.required_permissions:
                if not self._has_permission(perm, perms):
                    return SkillResult(
                        success=False,
                        error="AUTH_002",
                        output=f"需要权限: {perm}",
                    )

        if self.requires_human_approval:
            request_id = await self._create_approval_request(
                tenant_id=tenant_id,
                user_id=user_context.get("user_id", "") if user_context else "",
                params=entities,
            )
            return SkillResult(
                success=False,
                error="PENDING_APPROVAL",
                output=f"该操作需要审批，申请单号: {request_id}",
                approval_request_id=request_id,
            )

        start = time.time()
        result = await self._do_execute(entities)
        result.latency_ms = (time.time() - start) * 1000
        return result

    @abstractmethod
    async def _do_execute(self, entities: dict) -> SkillResult:
        ...

    def _has_permission(self, required: str, user_perms: list[str]) -> bool:
        if "admin:*" in user_perms:
            return True
        for up in user_perms:
            if up.endswith(":*"):
                resource = up.split(":")[0]
                if required.startswith(resource + ":") or required == resource:
                    return True
            if up == required:
                return True
        return False

    async def _create_approval_request(
        self, tenant_id: str, user_id: str, params: dict
    ) -> str:
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            row = session.execute(
                text(
                    """
                    INSERT INTO approval_requests
                        (tenant_id, user_id, resource, resource_type,
                         action, params, status, timeout_at)
                    VALUES
                        (:tid, :uid, :res, 'skill',
                         'execute', CAST(:params AS json), 'pending',
                         now() + interval '1 hour')
                    RETURNING id
                    """
                ),
                {
                    "tid": tenant_id,
                    "uid": user_id,
                    "res": f"skill:{self.id}",
                    "params": json.dumps(params, ensure_ascii=False),
                },
            ).fetchone()
            session.commit()
        return f"apr_{tenant_id}_{row.id}"
