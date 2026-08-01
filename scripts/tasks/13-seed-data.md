# Task 13: Seed 数据 + Mock 剧本

> ⚠️ Embedding 用 `np.random.seed(42); np.random.randn(1536).tolist()`，**不是**全零向量。
> **前置依赖:** `tasks/01-pgvector-migration.md`, `tasks/02-auth-rbac.md`
> **完成后:** 可以手动测试全流程了

## Subtask 13.01: seed_api_keys.py

**文件:** `scripts/seed_api_keys.py`
```python
import hashlib, secrets

def create_key(tenant_id, user_id, role):
    key = f"cg_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    # INSERT INTO api_keys
    print(f"{role}: {key}")
    return key
```

创建:
- 2 个租户（acme, beta）各 1 个 user key
- 1 个 super_admin key
- 1 个 auditor key
- 1 个 tenant_admin key

## Subtask 13.02: seed_pgvector.py

**文件:** `scripts/seed_pgvector.py`
- 写入示例对话数据
- 写入示例记忆数据
- Embedding 用 `np.random.seed(42); np.random.randn(1536).tolist()`

## Subtask 13.03: Mock 场景 YAML

**文件:**
- `data/mock_data/scenarios/working_anxiety.yaml`
- `data/mock_data/scenarios/heartbreak.yaml`
- `data/mock_data/scenarios/happy.yaml`
- `data/mock_data/scenarios/advice.yaml`
- `data/mock_data/scenarios/injection_attack.yaml`

格式:
```yaml
- scenario: "工作焦虑"
  turns:
    - user: "最近项目压力好大"
      emotion: "焦虑", intensity: 8
      intent: "emotion"
      response: "听起来你最近..."
```

## 验证

```bash
uv run python scripts/seed_api_keys.py  # → 输出 key
uv run python scripts/seed_pgvector.py  # → 表有数据
```
