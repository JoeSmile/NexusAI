"""MCP server persistence — DB CRUD + env merge (Task 67 slice 2)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from packages.security.url_guard import validate_base_url
from packages.capability.mcp_registry import McpServerConfig, load_mcp_servers_from_env

logger = logging.getLogger(__name__)

_TEST_MEM: dict[str, dict[str, Any]] = {}


@dataclass
class McpServerRecord:
    id: str
    tenant_id: str = "*"
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    allow_pass_user_context: bool = False
    timeout_s: float = 30.0
    last_probe: dict[str, Any] | None = None
    source: str = "db"

    def to_config(self) -> McpServerConfig:
        return McpServerConfig(
            id=self.id,
            transport=self.transport,
            command=self.command,
            args=list(self.args),
            env=dict(self.env),
            url=self.url,
            headers=dict(self.headers),
            enabled=self.enabled,
            allow_pass_user_context=self.allow_pass_user_context,
            timeout_s=float(self.timeout_s),
        )

    def to_public_dict(self, *, mask_secrets: bool = True) -> dict[str, Any]:
        headers_view: dict[str, str] = {}
        for key in self.headers:
            headers_view[key] = "***" if mask_secrets and self.headers.get(key) else ""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "url": self.url,
            "headers": headers_view,
            "header_keys": sorted(self.headers.keys()),
            "enabled": self.enabled,
            "allow_pass_user_context": self.allow_pass_user_context,
            "timeout_s": self.timeout_s,
            "last_probe": dict(self.last_probe or {}),
            "source": self.source,
        }


def _encrypt_headers(headers: dict[str, str]) -> str | None:
    if not headers:
        return None
    try:
        from packages.key_manager import KeyManager

        return KeyManager().encrypt(json.dumps(headers, ensure_ascii=False))
    except Exception as exc:
        logger.warning("mcp headers encrypt skipped: %s", exc)
        return None


def _decrypt_headers(blob: str | None) -> dict[str, str]:
    if not blob:
        return {}
    try:
        from packages.key_manager import KeyManager

        raw = json.loads(KeyManager().decrypt(blob))
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
    except Exception as exc:
        logger.warning("mcp headers decrypt skipped: %s", exc)
    return {}


def _row_to_record(row: Any, *, source: str = "db") -> McpServerRecord:
    return McpServerRecord(
        id=str(row.id),
        tenant_id=str(row.tenant_id or "*"),
        transport=str(row.transport or "stdio"),
        command=str(row.command or ""),
        args=[str(a) for a in (row.args or [])],
        env={str(k): str(v) for k, v in dict(row.env or {}).items()},
        url=str(row.url or ""),
        headers=_decrypt_headers(getattr(row, "headers_encrypted", None)),
        enabled=bool(row.enabled),
        allow_pass_user_context=bool(row.allow_pass_user_context),
        timeout_s=float(row.timeout_s or 30),
        last_probe=dict(row.last_probe) if row.last_probe else None,
        source=source,
    )


def _validate_record_payload(
    *,
    transport: str,
    command: str,
    url: str,
) -> None:
    t = transport.strip().lower()
    if t == "http":
        validate_base_url(url)
    elif t == "stdio" and not command.strip():
        raise ValueError("stdio_command_required")


def list_mcp_server_records() -> list[McpServerRecord]:
    records: list[McpServerRecord] = []
    try:
        from backend.database.pgvector_session import McpServer, get_pg_session

        pg = get_pg_session()
        with pg.get_session() as session:
            for row in session.query(McpServer).order_by(McpServer.id).all():
                records.append(_row_to_record(row))
    except Exception as exc:
        logger.info("mcp_servers DB list skipped: %s", exc)
        for raw in _TEST_MEM.values():
            records.append(McpServerRecord(**raw, source="db"))
    return records


def get_mcp_server_record(server_id: str) -> McpServerRecord | None:
    try:
        from backend.database.pgvector_session import McpServer, get_pg_session

        pg = get_pg_session()
        with pg.get_session() as session:
            row = session.query(McpServer).filter(McpServer.id == server_id).first()
            if row is not None:
                return _row_to_record(row)
    except Exception as exc:
        logger.debug("mcp_servers DB get skipped: %s", exc)
    raw = _TEST_MEM.get(server_id)
    if raw:
        return McpServerRecord(**raw, source="db")
    return None


def load_all_mcp_servers() -> list[McpServerConfig]:
    """Env servers first; DB record with same id overrides env."""
    merged: dict[str, McpServerConfig] = {
        cfg.id: cfg for cfg in load_mcp_servers_from_env()
    }
    for rec in list_mcp_server_records():
        merged[rec.id] = rec.to_config()
    return list(merged.values())


def upsert_mcp_server_record(
    *,
    server_id: str,
    tenant_id: str = "*",
    transport: str,
    command: str = "",
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    url: str = "",
    headers: dict[str, str] | None = None,
    enabled: bool = True,
    allow_pass_user_context: bool = False,
    timeout_s: float = 30.0,
    merge_headers: bool = True,
) -> McpServerRecord:
    _validate_record_payload(transport=transport, command=command, url=url)
    existing = get_mcp_server_record(server_id)
    merged_headers = dict(existing.headers if existing and merge_headers else {})
    if headers is not None:
        for key, value in headers.items():
            if value == "***" and key in merged_headers:
                continue
            merged_headers[str(key)] = str(value)

    record = McpServerRecord(
        id=server_id,
        tenant_id=tenant_id,
        transport=transport.strip().lower(),
        command=command,
        args=list(args or []),
        env=dict(env or {}),
        url=url,
        headers=merged_headers,
        enabled=enabled,
        allow_pass_user_context=allow_pass_user_context,
        timeout_s=float(timeout_s),
        last_probe=existing.last_probe if existing else None,
        source="db",
    )
    enc = _encrypt_headers(record.headers)
    try:
        from backend.database.pgvector_session import McpServer, get_pg_session

        pg = get_pg_session()
        with pg.get_session() as session:
            row = session.query(McpServer).filter(McpServer.id == server_id).first()
            if row is None:
                row = McpServer(id=server_id)
                session.add(row)
            row.tenant_id = record.tenant_id
            row.transport = record.transport
            row.command = record.command
            row.args = record.args
            row.env = record.env
            row.url = record.url
            row.headers_encrypted = enc
            row.enabled = record.enabled
            row.allow_pass_user_context = record.allow_pass_user_context
            row.timeout_s = record.timeout_s
            row.updated_at = datetime.utcnow()
            session.commit()
    except Exception as exc:
        logger.warning("mcp_servers DB upsert skipped for %s: %s", server_id, exc)
        _TEST_MEM[server_id] = {
            "id": record.id,
            "tenant_id": record.tenant_id,
            "transport": record.transport,
            "command": record.command,
            "args": record.args,
            "env": record.env,
            "url": record.url,
            "headers": record.headers,
            "enabled": record.enabled,
            "allow_pass_user_context": record.allow_pass_user_context,
            "timeout_s": record.timeout_s,
            "last_probe": record.last_probe,
        }
    return record


def delete_mcp_server_record(server_id: str) -> bool:
    deleted = False
    try:
        from backend.database.pgvector_session import McpServer, get_pg_session

        pg = get_pg_session()
        with pg.get_session() as session:
            row = session.query(McpServer).filter(McpServer.id == server_id).first()
            if row is not None:
                session.delete(row)
                session.commit()
                deleted = True
    except Exception as exc:
        logger.warning("mcp_servers DB delete skipped: %s", exc)
    if server_id in _TEST_MEM:
        del _TEST_MEM[server_id]
        deleted = True
    return deleted


def save_mcp_server_probe(server_id: str, probe: dict[str, Any]) -> None:
    probe = {**probe, "tested_at": datetime.utcnow().isoformat()}
    try:
        from backend.database.pgvector_session import McpServer, get_pg_session

        pg = get_pg_session()
        with pg.get_session() as session:
            row = session.query(McpServer).filter(McpServer.id == server_id).first()
            if row is not None:
                row.last_probe = probe
                row.updated_at = datetime.utcnow()
                session.commit()
    except Exception as exc:
        logger.debug("mcp probe persist skipped: %s", exc)
    if server_id in _TEST_MEM:
        _TEST_MEM[server_id]["last_probe"] = probe


def reset_mcp_store_for_tests() -> None:
    _TEST_MEM.clear()


def resolve_mcp_server_config(server_id: str) -> McpServerConfig:
    from packages.capability.mcp_errors import McpError, McpErrorCode

    for cfg in load_all_mcp_servers():
        if cfg.id == server_id:
            return cfg
    raise McpError(
        code=McpErrorCode.MCP_NOT_CONFIGURED.value,
        message="mcp_server_not_found",
        inner_error=server_id,
        retryable=False,
    )
