#!/usr/bin/env python3
"""创建初始 API Key — 开发环境使用"""

import hashlib
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.database.pgvector_session import get_pg_session

KEYS_TO_CREATE = [
    {"tenant_id": "acme", "user_id": "alice", "role": "user", "description": "Acme 租户用户 Alice"},
    {"tenant_id": "beta", "user_id": "bob", "role": "user", "description": "Beta 租户用户 Bob"},
    {"tenant_id": "*", "user_id": "admin", "role": "super_admin", "description": "全局管理员"},
    {"tenant_id": "*", "user_id": "auditor1", "role": "auditor", "description": "全局审计员"},
    {"tenant_id": "acme", "user_id": "admin_acme", "role": "tenant_admin", "description": "Acme 租户管理员"},
]


def create_key(tenant_id: str, user_id: str, role: str, description: str = "") -> str:
    raw_key = f"cg_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        # 按 user+tenant+role 去重，避免重复 seed
        existing = session.execute(
            text(
                "SELECT id FROM api_keys WHERE tenant_id=:tid AND user_id=:uid AND role=:role AND is_active=true LIMIT 1"
            ),
            {"tid": tenant_id, "uid": user_id, "role": role},
        ).fetchone()
        if existing:
            print(f"{'  [SKIPPED]':12s} {role:15s} {tenant_id:10s} {user_id:10s} (already exists)")
            return ""

        session.execute(
            text(
                """
                INSERT INTO api_keys (tenant_id, user_id, key_hash, key_prefix, role, description, created_by, is_active, created_at)
                VALUES (:tid, :uid, :hash, :prefix, :role, :desc, 'seed_script', true, now())
                """
            ),
            {
                "tid": tenant_id,
                "uid": user_id,
                "hash": key_hash,
                "prefix": key_prefix,
                "role": role,
                "desc": description,
            },
        )
        session.commit()

    print(f"{'  [CREATED]':12s} {role:15s} {tenant_id:10s} {user_id:10s} {raw_key}")
    return raw_key


def main():
    print("=" * 70)
    print("  ContextGate — Seed API Keys")
    print("=" * 70)
    print(f"\n{'Status':12s} {'Role':15s} {'Tenant':10s} {'User':10s} {'API Key'}")
    print("-" * 70)

    keys = {}
    for k in KEYS_TO_CREATE:
        raw = create_key(k["tenant_id"], k["user_id"], k["role"], k["description"])
        if raw:
            keys[f"{k['role']}:{k['user_id']}"] = raw

    print("-" * 70)
    if keys:
        print("\n🔑 保存以下 Key（仅显示一次）：\n")
        for role, key in keys.items():
            print(f"  {role:20s}: {key}")
        print("\n⚠️  这些 Key 不会再次显示！请立即保存到安全位置。")
    print("=" * 70)


if __name__ == "__main__":
    main()
