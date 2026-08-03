#!/usr/bin/env python3
"""创建/轮换开发 API Key + 测试账号 — 可重复运行。

每次运行都会为每个槽位生成**新的** cg_ key 并打印明文:
- 同槽位已存在 active key → 先停用(轮换),再插入新 key;
- 因此重复 seed 不会 SKIPPED,每次跑完都有一套可用 key。
同时 upsert 同名测试账号(users 表,密码统一 bcrypt("123456")),供密码登录使用。
明文 key 仍只存 stdout(数据库只存 SHA256 哈希,丢了不可恢复)。
"""

import hashlib
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.core.auth.password import hash_password
from backend.database.pgvector_session import get_pg_session

# 测试账号统一密码(Task 38 拍板:方便测试)
TEST_PASSWORD = "123456"

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
        # 同槽位已有 active key → 轮换:停用旧的,再插入新的(保证每次 seed 都有新 key 可用)
        existing = session.execute(
            text(
                "SELECT id FROM api_keys WHERE tenant_id=:tid AND user_id=:uid AND role=:role AND is_active=true LIMIT 1"
            ),
            {"tid": tenant_id, "uid": user_id, "role": role},
        ).fetchone()
        status = "CREATED"
        if existing:
            session.execute(
                text(
                    "UPDATE api_keys SET is_active=false, expires_at=now() WHERE id=:id"
                ),
                {"id": existing[0]},
            )
            status = "ROTATED"

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

    print(f"  [{status:7s}] {role:15s} {tenant_id:10s} {user_id:10s} {raw_key}")
    return raw_key


def seed_users(entries: list[dict]) -> None:
    """upsert 测试账号(users 表),密码统一 bcrypt(TEST_PASSWORD)。

    user_id = username = 身份标识(memory_hub 按 user_id 查画像,兼容);
    已存在 → 刷新密码/角色/租户(保证重跑后密码仍为 123456);不存在 → 插入。
    """
    password_hash = hash_password(TEST_PASSWORD)
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        for e in entries:
            session.execute(
                text(
                    """
                    INSERT INTO users (user_id, username, password_hash, display_name, tenant_id, role, is_active, created_at, updated_at)
                    VALUES (:uid, :username, :hash, :display, :tid, :role, true, now(), now())
                    ON CONFLICT (user_id) DO UPDATE SET
                        username      = EXCLUDED.username,
                        password_hash = EXCLUDED.password_hash,
                        display_name  = EXCLUDED.display_name,
                        tenant_id     = EXCLUDED.tenant_id,
                        role          = EXCLUDED.role,
                        is_active     = true,
                        updated_at    = now()
                    """
                ),
                {
                    "uid": e["user_id"],
                    "username": e["user_id"],
                    "hash": password_hash,
                    "display": e["description"],
                    "tid": e["tenant_id"],
                    "role": e["role"],
                },
            )
        session.commit()
    print(f"  ✅ 测试账号已同步 ({len(entries)} 个,密码统一 {TEST_PASSWORD})")


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
    seed_users(KEYS_TO_CREATE)
    print("-" * 70)
    if keys:
        print("\n🔑 本次运行生成的 Key(重复 seed 会轮换出新 key,旧 key 自动停用):\n")
        for role, key in keys.items():
            print(f"  {role:20s}: {key}")
        print("\n⚠️  明文只显示在 stdout,数据库仅存 SHA256 哈希——请立即保存到安全位置。")
    print("=" * 70)


if __name__ == "__main__":
    main()
