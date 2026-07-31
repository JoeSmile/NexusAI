"""
LLM API Key 加密管理器 — AES-256-GCM。

使用方式:
  manager = KeyManager()
  encrypted = manager.encrypt("sk-xxx...")
  plaintext = manager.decrypt(encrypted)

安全约束:
  - 单次 encrypt 返回 base64(nonce + ciphertext + tag)
  - 单次 decrypt 验证 GCM tag → 篡改检测
  - 明文绝不进日志、不持久化
  - Master key 从 LLM_KEY_MASTER_KEY 环境变量读取
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyManager:
    """AES-256-GCM 加密/解密 LLM API Key"""

    def __init__(self, master_key: str | None = None):
        key_hex = master_key or os.environ.get("LLM_KEY_MASTER_KEY")
        if not key_hex:
            raise RuntimeError(
                "LLM_KEY_MASTER_KEY 未设置 — 请生成 64 字符密钥: "
                "python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        key_bytes = bytes.fromhex(key_hex)
        if len(key_bytes) != 32:
            raise ValueError("LLM_KEY_MASTER_KEY 必须为 32 字节（64 hex 字符）")
        self._aesgcm = AESGCM(key_bytes)

    def encrypt(self, plaintext: str) -> str:
        """加密 → base64(nonce(12B) + ciphertext + tag(16B))"""
        nonce = os.urandom(12)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, encrypted_b64: str) -> str:
        """解密 ← base64 → 验证 GCM tag"""
        raw = base64.b64decode(encrypted_b64)
        nonce, ct = raw[:12], raw[12:]
        return self._aesgcm.decrypt(nonce, ct, None).decode()

    def re_encrypt(self, encrypted_b64: str, new_master_key_hex: str) -> str:
        """用当前 master key 解密，用新 key 重新加密（轮转用）"""
        plaintext = self.decrypt(encrypted_b64)
        return KeyManager(master_key=new_master_key_hex).encrypt(plaintext)
