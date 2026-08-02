"""admin 创建 API Key SQL 形状回归（EVID-12 / Task 25.08）"""

from __future__ import annotations

from pathlib import Path


def test_create_api_key_insert_sets_is_active_and_created_at():
    src = Path("backend/routers/admin.py").read_text(encoding="utf-8")
    # 锚定 create_api_key 附近的 INSERT，避免误匹配其它语句
    assert "async def create_api_key" in src
    idx = src.index("async def create_api_key")
    chunk = src[idx : idx + 1200]
    assert "INSERT INTO api_keys" in chunk
    assert "is_active" in chunk
    assert "created_at" in chunk
    assert "true, now()" in chunk or "true,now()" in chunk.replace(" ", "")
