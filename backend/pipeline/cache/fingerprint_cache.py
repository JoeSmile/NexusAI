"""意图指纹缓存 — 跨用户复用"""

from __future__ import annotations

import hashlib
import json


def make_fingerprint(intent: str, entities: dict) -> str:
    """生成意图指纹"""
    normalized = {k: _normalize_entity(k, v) for k, v in entities.items()}
    sorted_str = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return f"{intent}:{hashlib.sha256(sorted_str.encode()).hexdigest()[:12]}"


def _normalize_entity(key: str, value) -> str:
    """标准化实体值"""
    location_map = {
        "北京": "beijing",
        "上海": "shanghai",
        "广州": "guangzhou",
        "深圳": "shenzhen",
        "杭州": "hangzhou",
    }
    if isinstance(value, str) and value in location_map:
        return location_map[value]
    return value if isinstance(value, str) else str(value)
