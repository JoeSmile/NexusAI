"""密码哈希工具 — bcrypt (Task 38.01)。

提供 `hash_password` / `verify_password`，供 `backend/routers/auth.py` 与
`scripts/seed_api_keys.py` 共用。cost=12 与 seed 脚本一致。
"""

from __future__ import annotations

import bcrypt

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """bcrypt 哈希 → str(UTF-8 解码,可直接写入 String 列)。"""
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文与 bcrypt 哈希;空哈希 / 异常一律返回 False。"""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
