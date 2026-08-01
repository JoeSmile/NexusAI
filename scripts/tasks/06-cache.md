# Task 06: 缓存系统（精确 + 指纹）

> ⚠️ Hash 用 `hashlib.sha256`，**不是** Python `hash()`。
> **前置依赖:** `tasks/04-langgraph-pipeline.md`（需要 pipeline 节点定义）
> **完成后:** 无（独立 Task）

## Subtask 06.01: 精确缓存

**文件:** `backend/pipeline/cache/exact_cache.py`
- key: `exact:{tenant}:{user}:{query_hash}` — TTL=5min
- 存 `cache_entries` 表
```python
def make_query_hash(message: str) -> str:
    return hashlib.sha256(message.encode()).hexdigest()[:16]
```

## Subtask 06.02: 指纹缓存

**文件:** `backend/pipeline/cache/fingerprint_cache.py`
- key: `template:{fingerprint}` — TTL=24h
- 跨用户复用

## Subtask 06.03: 意图指纹生成

**文件:** `backend/pipeline/cache/intent_fingerprint.py`
```python
def make_fingerprint(intent: str, entities: dict) -> str:
    normalized = {k: _normalize_entity(k, v) for k, v in entities.items()}
    sorted_str = json.dumps(normalized, sort_keys=True)
    return f"{intent}:{hashlib.sha256(sorted_str.encode()).hexdigest()[:12]}"

def _normalize_entity(key: str, value: str) -> str:
    """标准化实体值: 北京/首都/京城 → beijing"""
    ...
```

## 验证

同一 query 发两次 → 第二次 < 10ms，`cache_hit=true`
