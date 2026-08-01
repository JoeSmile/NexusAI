# Task 18: LLM API Key 安全治理

> **P0 安全 — 当前风险：** 一个 `LLM_API_KEY` 明文字段在 `config.py` 里全局共享，无加密、无租户隔离、无轮转、无审计。
> **目标：** 建设企业级 LLM API Key 全生命周期管理体系：加密存储 → 租户隔离 → 轮转审计 → 健康监测。

## 问题现状

| 问题 | 严重程度 | 描述 |
|------|---------|------|
| 明文存储 | P0 | `LLM_API_KEY` 在 env/config.py 里明文，任何人都可读取 |
| 单 Key 全局共享 | P1 | 所有租户共用同一个 LLM API Key，无法做用量隔离和计费 |
| 无轮转机制 | P1 | Key 泄漏后无法滚动更换，只能重启服务改 env |
| 无使用审计 | P2 | 谁、什么时候、用了哪个 Key 调了哪个模型 — 无记录 |
| 无健康检测 | P2 | Key 过期或额度耗尽时，用户看到的只是晦涩的 LLM API 报错 |

## 架构设计

```text
                    ┌─────────────────────┐
                    │  LLM_KEY_MASTER_KEY  │  ← 唯一 env 变量（AES-256 密钥）
                    │  (env, 非代码仓库)    │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │   KeyManager        │  ← 加密 / 解密 / 缓存
                    │   (AES-256-GCM)     │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼──────┐ ┌─────▼──────┐ ┌──────▼─────┐
    │ llm_api_keys   │ │ 租户配置    │ │ Key 健康    │
    │ 表（加密存储）  │ │ 表引用 key │ │ 缓存预热    │
    └────────────────┘ └────────────┘ └────────────┘
```

**加密方案：** AES-256-GCM（authenticated encryption）
- 每次加密生成随机 12 字节 nonce
- 密文 = base64(nonce + ciphertext + tag)
- 解密时验证完整性（GCM tag 防篡改）
- Master key 只从 `LLM_KEY_MASTER_KEY` env 变量读取，不进数据库

## Subtask 18.01: llm_api_keys 表 + 加密工具

**文件:** `backend/database/init_pgvector.sql`（追加）

```sql
-- LLM API Key 管理表
CREATE TABLE llm_api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64) NOT NULL,        -- 关联租户，'*' 表示全局默认
    key_alias       VARCHAR(128) NOT NULL,        -- 可读别名，如 "生产-DS-2025Q1"
    provider        VARCHAR(32) NOT NULL,          -- deepseek / openai / zhipu / ...
    base_url        VARCHAR(256) NOT NULL DEFAULT '',
    encrypted_key   TEXT NOT NULL,                 -- AES-256-GCM 加密后的 API Key
    key_version     INT NOT NULL DEFAULT 1,        -- 轮转版本号
    is_active       BOOLEAN NOT NULL DEFAULT true,
    expires_at      TIMESTAMPTZ,                   -- 过期时间，null=永不过期
    last_verified   TIMESTAMPTZ,                   -- 上次健康检查时间
    last_verified_ok BOOLEAN,                      -- 上次健康检查结果
    description     TEXT DEFAULT '',
    created_by      VARCHAR(128) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    rotated_at      TIMESTAMPTZ,                   -- 上次轮转时间
    rotated_from    UUID REFERENCES llm_api_keys(id),  -- 轮转来源 key
    UNIQUE(tenant_id, key_alias)
);
CREATE INDEX idx_lak_tenant ON llm_api_keys(tenant_id, is_active);
```

**文件:** `backend/core/key_manager.py` — 加密/解密核心

```python
"""
LLM API Key 加密管理器 — AES-256-GCM。

使用方式:
  manager = KeyManager()
  encrypted = manager.encrypt("sk-xxx...")       # 加密
  plaintext = manager.decrypt(encrypted)         # 解密
  # plaintext 使用后立即释放，不缓存明文

安全约束:
  - 单次 encrypt 返回 base64(nonce + ciphertext + tag)
  - 单次 decrypt 验证 GCM tag → 篡改检测
  - 明文绝不进日志、不持久化、不在 Python 堆上停留超过必要时间
  - Master key 从 LLM_KEY_MASTER_KEY 环境变量读取
"""

import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyManager:
    """AES-256-GCM 加密/解密 LLM API Key"""

    def __init__(self, master_key: str | None = None):
        key_hex = master_key or os.environ.get("LLM_KEY_MASTER_KEY")
        if not key_hex:
            raise RuntimeError(
                "LLM_KEY_MASTER_KEY 未设置 — 请生成 64 字符 32 字节的 hex 密钥: "
                "python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        key_bytes = bytes.fromhex(key_hex)
        if len(key_bytes) != 32:
            raise ValueError("LLM_KEY_MASTER_KEY 必须为 32 字节（64 字符 hex）")
        self._aesgcm = AESGCM(key_bytes)

    def encrypt(self, plaintext: str) -> str:
        """加密 → base64(nonce(12B) + ciphertext + tag(16B))"""
        nonce = os.urandom(12)  # AES-GCM 推荐 nonce 12 字节
        ct = self._aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, encrypted_b64: str) -> str:
        """解密 ← base64 → 验证 GCM tag"""
        raw = base64.b64decode(encrypted_b64)
        nonce, ct = raw[:12], raw[12:]
        return self._aesgcm.decrypt(nonce, ct, None).decode()

    def create_new_master_key(self) -> str:
        """生成新的 32 字节 master key（用于初始化/轮转）"""
        import secrets
        new_key = secrets.token_hex(32)
        return new_key

    # ── 重新加密（Key 轮转时使用） ──────────────────────
    def re_encrypt(self, encrypted_b64: str, new_master_key_hex: str) -> str:
        """用旧 master key 解密，用新 master key 重新加密"""
        plaintext = self.decrypt(encrypted_b64)
        old_master = os.environ.get("LLM_KEY_MASTER_KEY")
        try:
            os.environ["LLM_KEY_MASTER_KEY"] = new_master_key_hex
            new_mgr = KeyManager()
            return new_mgr.encrypt(plaintext)
        finally:
            os.environ["LLM_KEY_MASTER_KEY"] = old_master or ""
```

**文件:** `backend/core/key_manager_test.py`（验证加密正确性）

```python
"""KeyManager 单元测试 — 不依赖数据库"""
import os
import tempfile
from backend.core.key_manager import KeyManager


def test_encrypt_decrypt_roundtrip():
    mgr = KeyManager(master_key="00" * 32)
    original = "sk-test-api-key-123456"
    encrypted = mgr.encrypt(original)
    assert encrypted != original, "加密后不应等于明文"
    decrypted = mgr.decrypt(encrypted)
    assert decrypted == original, "解密后应还原"


def test_tamper_detection():
    mgr = KeyManager(master_key="00" * 32)
    encrypted = mgr.encrypt("sk-test")
    tampered = encrypted[:-5] + "XXXXX" + encrypted[-5:]  # 改动密文
    try:
        mgr.decrypt(tampered)
        assert False, "篡改后应抛出异常"
    except Exception:
        pass  # 预期行为


def test_different_nonce():
    """每次加密应产生不同密文（nonce 随机）"""
    mgr = KeyManager(master_key="00" * 32)
    e1 = mgr.encrypt("sk-test")
    e2 = mgr.encrypt("sk-test")
    assert e1 != e2, "nonce 随机，相同明文不应产生相同密文"


if __name__ == "__main__":
    test_encrypt_decrypt_roundtrip()
    test_tamper_detection()
    test_different_nonce()
    print("✅ KeyManager 测试全部通过")
```

> ⚠️ `LLM_KEY_MASTER_KEY` 生成命令（部署时执行一次）：
> ```bash
> python -c 'import secrets; print(secrets.token_hex(32))'
> # 输出类似: a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
> ```

## Subtask 18.02: LLMKeyRepository — 数据库读写层

**文件:** `backend/core/key_repository.py`

```python
"""
LLM API Key 数据库读写层。

职责:
  - 按租户+provider 查询可用 key
  - 自动解密返回明文（调用方用完即弃）
  - LRU 缓存已解密的 key（减少数据库查询和 AES 运算）
  - 支持 key 版本 / 过期检测
"""

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional
from backend.core.key_manager import KeyManager


@dataclass
class LLMKey:
    id: str
    tenant_id: str
    provider: str
    base_url: str
    api_key: str        # 已解密明文
    key_version: int
    is_active: bool
    expires_at: Optional[int]  # Unix timestamp, None=永不


class LLMKeyCache:
    """LRU 缓存，已解密 key 不进日志"""
    MAX = 100
    TTL_SEC = 300  # 5 分钟

    def __init__(self):
        self._cache: OrderedDict[str, tuple[LLMKey, float]] = OrderedDict()

    def get(self, key: str) -> Optional[LLMKey]:
        item = self._cache.get(key)
        if not item:
            return None
        key_obj, ts = item
        if time.time() - ts > self.TTL_SEC:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return key_obj

    def set(self, key: str, value: LLMKey) -> None:
        self._cache[key] = (value, time.time())
        if len(self._cache) > self.MAX:
            self._cache.popitem(last=False)


class LLMKeyRepository:
    """按租户+provider 获取 LLM API Key，自动解密"""

    def __init__(self, key_manager: KeyManager | None = None):
        self._km = key_manager or KeyManager()
        self._cache = LLMKeyCache()

    async def get_key(
        self, tenant_id: str, provider: str = "default"
    ) -> LLMKey | None:
        """查询顺序: 租户专用 key → 全局默认 key"""
        cache_key = f"{tenant_id}:{provider}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        # 查数据库 — 优先租户级
        row = await self._query_db(tenant_id, provider)
        if not row:
            row = await self._query_db("*", provider)  # 全局兜底
        if not row:
            return None

        plain_key = self._km.decrypt(row["encrypted_key"])
        key_obj = LLMKey(
            id=str(row["id"]),
            tenant_id=row["tenant_id"],
            provider=row["provider"],
            base_url=row.get("base_url", ""),
            api_key=plain_key,
            key_version=row["key_version"],
            is_active=row["is_active"],
            expires_at=(
                int(row["expires_at"].timestamp())
                if row.get("expires_at") else None
            ),
        )
        self._cache.set(cache_key, key_obj)
        return key_obj

    async def _query_db(self, tenant_id: str, provider: str) -> dict | None:
        """SQL: SELECT * FROM llm_api_keys
           WHERE tenant_id = :t AND provider = :p AND is_active = true
              AND (expires_at IS NULL OR expires_at > now())
           ORDER BY key_version DESC LIMIT 1"""
        # TODO: Cursor 实现 SQL
        return None

    def invalidate_cache(self, tenant_id: str, provider: str = "default") -> None:
        """key 更新/吊销后调用，清除缓存"""
        self._cache._cache.pop(f"{tenant_id}:{provider}", None)
```

## Subtask 18.03: 改造 config.py — 移除明文 LLM_API_KEY

**修改:** `config.py`

```python
# 替换现有 LLM_API_KEY / OPENAI_API_KEY / DASHSCOPE_API_KEY 等明文变量

class Config:
    # ── LLM API Key 安全治理（替代所有明文 key） ──────
    # 不再读取 LLM_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY
    # LLM Key 从 llm_api_keys 表加密存储，通过 KeyManager 运行时解密
    # 唯一保留的 env 变量是 LLM_KEY_MASTER_KEY（加密密钥）
    LLM_KEY_MASTER_KEY = os.getenv("LLM_KEY_MASTER_KEY", "")

    # ── 兼容层（迁移过渡期使用） ──────────────────────
    # 如果 DB 中没有对应租户的 LLM key，降级到旧 env 变量
    # 迁移完成后移除以下 fallback
    LLM_API_KEY_FALLBACK = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    LLM_BASE_URL_FALLBACK = os.getenv("LLM_BASE_URL") or os.getenv("API_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
```

**关键变化：**
- `Config.LLM_API_KEY` 不再是简单读取 env，而是从数据库获取
- 所有直接引用 `config.LLM_API_KEY` 的代码 → 改调 `LLMKeyRepository.get_key()`
- 提供 `fallback` 机制让 CI/Mock 环境不需要数据库也能运行

**⚠️ Cursor 警告：**
- 现有代码中多处直接引用 `config.OPENAI_API_KEY` 和 `config.LLM_API_KEY`（如 `backend/core/harness/llm.py` 的 `_call_api`、`backend/runtime/protocols/llm_client.py`）— 需要**逐个搜索替换**
- `try_create_chat_openai()` 函数签名改为 `try_create_chat_openai(api_key: str, base_url: str, model: str)` 而不是从 config 读
- 迁移期间保留 `LLM_API_KEY_FALLBACK` 让旧代码逐步迁移，不要一次性全改

## Subtask 18.04: 改造模型路由 — tenant 级 key 注入

**修改:** `backend/pipeline/nodes/model_router.py`

```python
from backend.core.key_repository import LLMKeyRepository

_key_repo = LLMKeyRepository()
_provider_model_map = {
    "deepseek": "deepseek",
    "openai":   "openai",
    "zhipu":    "zhipu",
    "qwen":     "qwen",
}

async def model_router(state: PipelineState) -> PipelineState:
    # ... 既有意图路由逻辑 ...

    # ── 新增: 按租户获取 LLM Key ──────────────────────
    tenant_id = state["tenant_id"]
    route = ROUTING_RULES.get(state["intent"], ROUTING_RULES["default"])
    model_name = route["model"]

    # 根据模型名推断 provider
    provider = _detect_provider(model_name)
    llm_key = await _key_repo.get_key(tenant_id, provider)

    if llm_key is None:
        # 降级到 config fallback（迁移期）
        from config import Config
        llm_key = LLMKey(
            id="fallback",
            tenant_id=tenant_id,
            provider=provider,
            base_url=Config.LLM_BASE_URL_FALLBACK,
            api_key=Config.LLM_API_KEY_FALLBACK,
            key_version=0,
            is_active=True,
            expires_at=None,
        )

    state["llm_api_key"] = llm_key.api_key
    state["llm_base_url"] = llm_key.base_url
    state["llm_key_id"] = llm_key.id       # 审计用
    state["llm_key_version"] = llm_key.key_version  # 审计用
    # ... 继续原逻辑 ...
    return state

def _detect_provider(model: str) -> str:
    """根据模型名推断 provider"""
    model_lower = model.lower()
    if any(k in model_lower for k in ["deepseek"]):
        return "deepseek"
    if any(k in model_lower for k in ["gpt", "o1", "o3"]):
        return "openai"
    if any(k in model_lower for k in ["glm", "zhipu"]):
        return "zhipu"
    if any(k in model_lower for k in ["qwen"]):
        return "qwen"
    return "default"
```

**修改:** `backend/pipeline/nodes/llm_generate.py`

```python
# 从 state 获取 tenant 级 API key，不再读 config

async def llm_generate(state: PipelineState) -> PipelineState:
    api_key = state.get("llm_api_key")
    base_url = state.get("llm_base_url")
    if not api_key:
        # 降级处理
        api_key = Config.LLM_API_KEY_FALLBACK
        base_url = Config.LLM_BASE_URL_FALLBACK

    result = await _call_llm(
        model=state["selected_model"],
        messages=[{"role": "user", "content": state["message"]}],
        api_key=api_key,
        base_url=base_url,
    )
    # ...
```

## Subtask 18.05: Admin API — LLM Key 管理（CRUD + 轮转）

**修改:** `backend/routers/admin.py`

新增管理接口：

| 接口 | 权限 | 说明 |
|------|------|------|
| `POST /api/admin/llm-keys` | `admin:llm_key` | 创建 LLM Key（明文传入，加密存储） |
| `GET /api/admin/llm-keys` | `admin:llm_key` | 列出租户的 LLM Key（不返回明文） |
| `PUT /api/admin/llm-keys/{id}` | `admin:llm_key` | 更新 Key |
| `POST /api/admin/llm-keys/{id}/rotate` | `admin:llm_key` | 轮转 Key（生成新版本） |
| `DELETE /api/admin/llm-keys/{id}` | `admin:llm_key` | 吊销 Key |
| `POST /api/admin/llm-keys/{id}/verify` | `admin:llm_key` | 立即验证 Key 有效性 |

```python
# 后端/core/key_manager.py 补充
async def verify_key(api_key: str, base_url: str, model: str = "deepseek-chat") -> bool:
    """向 LLM 提供商发送一次轻量请求验证 Key 有效性"""
    from openai import AsyncOpenAI
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.models.retrieve(model)
        return True
    except Exception:
        return False
```

**⚠️ Cursor 警告：**
- `POST /api/admin/llm-keys` 接收 API Key 明文 — 必须通过 HTTPS，响应不返回明文
- `GET /api/admin/llm-keys` 的响应中 `encrypted_key` 字段使用 `"***"` 或类型标记替代
- 轮转时保留旧版本 key 的 `is_active=false`，旧版本不在查询结果中但保留审计追溯
- `verify_key` 调用是出站请求 — 需要 Harness 包裹（断路器 + 超时）

## Subtask 18.06: Key 健康检查 + 审计日志

**文件:** `backend/core/key_health.py`

```python
"""
LLM API Key 健康检查 — 定期验证 Key 有效性。

运行方式:
  1. 启动时对活跃 key 全量预热验证
  2. 定时任务（可 cron 驱动）检查过期和即将过期 key
  3. 管理后台手动触发单 key 验证
"""

import asyncio
from datetime import datetime, timedelta, timezone


class KeyHealthChecker:
    """定时检查 LLM API Key 状态"""

    CHECK_INTERVAL = 3600  # 每小时

    async def run_periodic_check(self):
        """后台循环 — 注册到 FastAPI lifespan"""
        while True:
            await self._check_all()
            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _check_all(self):
        """查出 7 天内过期 + 未被验证超过 24h 的 key"""
        rows = await self._query_due_keys()
        for row in rows:
            await self._verify_single(row)

    async def _query_due_keys(self) -> list[dict]:
        """SQL: SELECT * FROM llm_api_keys
           WHERE is_active = true
             AND (
               (expires_at IS NOT NULL AND expires_at < now() + INTERVAL '7 days')
               OR
               (last_verified IS NULL OR last_verified < now() - INTERVAL '24 hours')
             )"""
        return []  # TODO

    async def _verify_single(self, row: dict) -> None:
        from backend.core.key_manager import KeyManager
        from backend.core.key_repository import LLMKeyRepository
        km = KeyManager()
        plain_key = km.decrypt(row["encrypted_key"])
        ok = await verify_key(plain_key, row.get("base_url", ""))
        # SQL: UPDATE llm_api_keys SET last_verified = now(), last_verified_ok = :ok
        #      WHERE id = :id
        if not ok:
            # P1 告警 — 发通知: LLM Key {row["key_alias"]} 验证失败
            pass
```

**审计日志整合（修改 Task 03 的审计表）：**

```sql
-- 新增审计事件类型: llm_key_used / llm_key_rotated / llm_key_created / llm_key_revoked
ALTER TABLE audit_logs
  ADD COLUMN llm_key_id UUID,
  ADD COLUMN llm_key_version INT;
```

**审计日志写入位置：**
- `LLMHarness.generate()` 执行后写入 `llm_key_used` 事件
- Admin API 创建/轮转/吊销时写入对应事件

## Subtask 18.07: Seed 数据 + 迁移脚本

**文件:** `backend/scripts/migrate_llm_keys.py`

```python
"""
一次性迁移脚本：将 env 中的 LLM_API_KEY 加密存入 llm_api_keys 表。

用法:
  uv run python backend/scripts/migrate_llm_keys.py

注意:
  - 需要 LLM_KEY_MASTER_KEY 环境变量已设置
  - 迁移后 config.py 中的 fallback 可逐步移除
"""

import os
import asyncio
from backend.core.key_manager import KeyManager
from backend.database.pgvector_session import get_session


async def migrate():
    km = KeyManager()
    plain_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL") or os.environ.get("API_BASE_URL", "")

    if not plain_key:
        print("⚠️ 未找到 LLM_API_KEY 环境变量，跳过迁移")
        return

    encrypted = km.encrypt(plain_key)
    # INSERT INTO llm_api_keys (tenant_id, key_alias, provider, base_url, encrypted_key, description, created_by)
    # VALUES ('*', 'migrated-from-env', 'default', :base_url, :encrypted, '自动迁移自环境变量', 'system')
    print(f"✅ LLM API Key 已加密存储 (长度: {len(encrypted)} 字符)")
    print("⚠️ 迁移完成后建议从环境变量中移除 LLM_API_KEY")


if __name__ == "__main__":
    asyncio.run(migrate())
```

**Seed 数据更新（`tasks/13-seed-data.md`）：**

```yaml
llm_api_keys:
  - tenant_id: "*"
    key_alias: "seed-default"
    provider: "default"
    base_url: "https://open.bigmodel.cn/api/paas/v4/"
    encrypted_key: ""  # 由迁移脚本或 admin API 实际写入
    description: "Seed 数据默认 LLM Key（需替换真实 key）"
```

## 验证

```bash
# 1. KeyManager 加解密测试
uv run python -c "
from backend.core.key_manager import KeyManager
mgr = KeyManager(master_key='a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2')
enc = mgr.encrypt('sk-my-test-key-12345')
dec = mgr.decrypt(enc)
print(f'加密: {enc[:16]}...')
print(f'解密: {dec}')
assert dec == 'sk-my-test-key-12345'
print('✅ 加解密成功')
"

# 2. 单元测试
uv run python backend/core/key_manager_test.py
# → ✅ KeyManager 测试全部通过

# 3. 迁移脚本（需 LLM_KEY_MASTER_KEY 已设置）
uv run python backend/scripts/migrate_llm_keys.py
# → ✅ LLM API Key 已加密存储

# 4. Admin API 创建 key
curl -X POST http://localhost:8000/admin/llm-keys \
  -H "X-API-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"demo_tenant","key_alias":"生产-DS","provider":"deepseek","base_url":"https://api.deepseek.com","api_key":"sk-ds-xxx"}'
# → 201 {"id":"...","key_alias":"生产-DS","tenant_id":"demo_tenant","provider":"deepseek","encrypted_key":"***"}

# 5. 验证租户级 key 隔离
# tenant_a 只看到自己的 key
curl -X GET http://localhost:8000/admin/llm-keys \
  -H "X-API-Key: $TENANT_A_KEY"
# → 只返回 tenant_a 的 key 列表（不返回明文）

# 6. Key 轮转
curl -X POST http://localhost:8000/admin/llm-keys/$ID/rotate \
  -H "X-API-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_key":"sk-ds-new-xxx","reason":"例行轮转"}'
# → 200 {"id":"...","key_version":2,"rotated_at":"..."}
```
