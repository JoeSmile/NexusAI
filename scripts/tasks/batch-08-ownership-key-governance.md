# Batch 8: 收尾 — 项目占领 + LLM API Key 安全治理

> **包含:** Task 17 (7 subtasks) + Task 18 (7 subtasks)  
> **预估:** 50-70 分钟  
> **依赖:** Batch 2 (auth) + Batch 4 (pipeline) + Batch 5b (model_router + harness)  
> ⚠️ **Task 18 是 P0 安全 — 改完立即消除明文 LLM_API_KEY 的风险**  
> **Commit 1:** `git add -A && git commit -m "feat: project ownership, docs, dev shell\n\nSigned-off-by: Joe"`
> **Commit 2:** `git add -A && git commit -m "feat: LLM API key governance with AES-256-GCM\n\nSigned-off-by: Joe"`

---

## Subtask 8.1: 质量门禁收尾（必须最先做）

> **目的:** 清理存量 lint/type 债务，让 CI 从"必红"变"全绿"。Batch 8 之后是发布，门禁必须过。
> **现状（2026-07-31 Hermes 实测核实）:**
> - ✅ Ruff 已收敛: `select=[E4,E7,E9,F,I,UP,B]`, `ignore=[E501,B008,B904,E402]`（pyproject.toml:135-147）→ `ruff check backend/ scripts/` **全绿**
> - ✅ MyPy 只严查主路径: `files=[pipeline, skills, observability, core/auth, core/guardrails, core/harness, core/*.py]`（pyproject.toml:163-177）→ **50 files, no issues**
> - ✅ plugins/ 已删，无 backend.plugins 残留引用（llm_with_plugins.py 已 stub，PluginManager 空实现）
> - ✅ backend/main.py 已删，无引用（run_backend.py 用 backend.app:app）
> - ✅ 8.1.5 缓存 key 实测带 tenant: `exact:{tenant_id}:{user_id}:{query_hash}` / `template:{tenant_id}:{fingerprint}`
> - ⏳ **chat_service.py 待拍板** — 原文档保留理由有误（事实修正见 8.1.1），等 Joe 决策
> - 📌 新发现见 8.1.7（不属本批门禁范围，记录待后续批次）

### 8.1.1 删除 plugins 死代码 + chat_service 拍板

```bash
# ✅ plugins/ 已删。仅需确认无残留引用（llm_with_plugins.py 已 stub）
grep -rln "backend.plugins\|from backend import plugins" backend/ --include="*.py" | grep -v __pycache__ || echo "✅ 无引用"
```

> ⏳ **chat_service.py — 已拍板: 选项 A 直接删（2026-07-31）**
>
> 原文档称"被 optional legacy router 引用（routers/__init__.py 的 try/except 导入）"，实测：
> - routers/__init__.py 的 try/except 导入的是 rag_router + agent_router，**与 chat 无关**
> - chat_router 由 routers/__init__.py:7 **无条件**导入；app.py:157 已注释 `# app.include_router(chat_router)  # DEPRECATED`，**从不挂载**
> - 每次启动都会执行 chat.py:36 模块级 `chat_service = ChatService()`，拉入整条旧链（llm_with_plugins → personalization_service → xinyu_prompt）
> - chat.py 唯一引用方是 routers/__init__.py:7；app.py:241 的 "ChatService" 只是 /system/info 展示字符串
>
> **✅ 已执行（选项 A）:**
> 1. 删除: `backend/routers/chat.py` + `backend/services/chat_service.py` + `backend/services/chat_service_integration_example.py` + `backend/dependencies.py`（零引用方的 ServiceContainer，直接引用已删 ChatService）
> 2. `routers/__init__.py`: 移除 chat_router import + __all__ 条目
> 3. `app.py`: 移除 DEPRECATED 注释行；/system/info services_list 去掉 "ChatService"
> 4. **连带修复**: `optimized_chat_service.py` 原为 `OptimizedChatService(ChatService)` 子类 — 实测父类属性从未被使用（self.llm_client/emotion_analyzer/safety_checker/memory_retriever 在整条继承链上都不存在），`super().__init__()` 纯属白跑（还实例化 RAG/jieba）。改为独立类，去掉继承。
> 5. **验证通过**: ruff 全绿 / mypy 50 files no issues / app import OK（82 routes）/ pytest 15 passed
>
> ```bash
> # 复验:
> uv run python -c "from backend.app import app; print('✅ app import OK')"
> ```

### 8.1.2 Ruff 批量自动修复 — ✅ 已完成

```bash
uv run ruff check backend/ scripts/   # → All checks passed!
```

### 8.1.3 手工修剩余 Ruff 错误 — ✅ 已完成（无需手工修）

> **原则（保留）:** 主路径（pipeline/skills/observability/core）必须 0 错误；遗留目录（agent/modules/services）允许 per-file-ignores 豁免，后续单独批次清理。

### 8.1.4 验证：质量门禁全绿 — ✅ 已通过（2026-07-31）

```bash
cd /Users/guowei/Desktop/github/contextgate

# 1. MyPy（主路径）→ Success: no issues found in 50 source files
uv run mypy

# 2. Ruff → All checks passed!
uv run ruff check backend/ scripts/

# 3. 全量测试（未跑，需要 postgres；DB 起来后补）
uv run pytest tests/ -v --tb=short

# 4. 启动冒烟（若执行 chat_service 删除，删除后重跑）
uv run python -c "
import sys; sys.path.insert(0, '.')
from backend.app import app
print('✅ app import OK')
"
```

### 8.1.5 缓存 key 安全确认 — ✅ 已通过（拍板项 A: 带 tenant）

**实现已核实:** `backend/pipeline/nodes/cache_check.py:47,70` + `write_memory.py:70,88`：

- ✅ 正确: `exact:{tenant_id}:{user_id}:{query_hash}` / `template:{tenant_id}:{fingerprint}`
- 无跨租户泄露风险

### 8.1.6 Commit — ✅ 已完成（1944d8d）

```bash
git add -A && git commit -m "chore: quality gate cleanup, remove legacy plugins, fix lint debt

Signed-off-by: Joe"
```

> chat_service 若按选项 A 删除，追加一个 commit（`refactor: remove dead chat router & chat_service`）。

### 8.1.7 新发现（记录待后续批次，不属本批门禁范围）

1. **cache_check 情绪域硬编码**: `backend/pipeline/nodes/cache_check.py:19-33` 的 `_cheap_fingerprint` 仍按情绪词表（焦虑/伤心/害怕/紧张/压力/孤独 → "emotion" 分支）做模板缓存预检，违反 ContextGate "无业务域情绪概念"原则。建议后续批次移除情绪分支，改通用意图归一化（或直接依赖 analyze_parallel 的 fingerprint）。
2. **mypy 主入口盲区**: `files` 列表未含 `backend/app.py` 与 `backend/routers/`。主入口本身不进类型门禁，建议下一批纳入 routers/ 或至少 app.py。
3. **OptimizedChatService 预存 AttributeError 隐患**（删 chat_service 时暴露）: `optimized_chat_service.py` 的 `self.llm_client / emotion_analyzer / safety_checker / memory_retriever` 在整条继承链上从未定义。当前不炸是因为 redis 不在依赖声明里（requirements.txt/pyproject.toml 均无），performance/streaming 路由被 app.py 的 try/except 静默关闭。**若未来安装 redis 并开启 PERFORMANCE_OPTIMIZATION_ENABLED，调用端点会 AttributeError** — 启用前必须先补这四个属性或重写该类。

---

## A. Task 17: 项目占领

### 17.01: 法律护城河

### 创建: `LICENSE`

```
Apache License 2.0

Copyright 2026 Joe

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

...
```

### 创建: `NOTICE`

```
ContextGate
Copyright 2026 Joe

This project is derived from emotional_chat (MIT License).
Original copyright notice preserved below:

MIT License
Copyright (c) 2025 emotional_chat
```

### 修改: `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
uv.lock

# Environment
.env
config.env
*.local.env

# Data
uploads/
data/
chroma_db/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
```

---

### 17.02: README 门面级重写

### 修改: `README.md`

```markdown
# ContextGate

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-green)]()
[![CI](https://github.com/joe/context-gate/actions/workflows/ci.yml/badge.svg)]()

> **The Intelligent Gateway for LLM Context Management**

企业级 LLM 前置处理管线 — 认证、多租户、安全护栏、可观测、模型路由、缓存、加密 Key 管理。

## Architecture

```
用户 → FastAPI → LangGraph StateGraph → pgvector → LangFuse
                ↑
      Auth(RBAC0) → Guardrails → Prometheus
```

管线节点：
```
auth_check → load_memory → rate_limiter → cache_check
  ├─ hit → END
  └─ miss → guardrails_input → analyze_parallel → build_context
            → model_router
              ├─ short path → execute skill → END (50ms)
              └─ long path → llm_generate → guardrails_output
                            → write_memory + audit → END (1-5s)
```

## Quick Start

```bash
# 1. 启动基础设施
docker compose -f docker-compose.local.yml up -d

# 2. 安装依赖
uv sync

# 3. 初始化数据
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_pgvector.py

# 4. 启动服务
uv run uvicorn backend.app:app --reload

# 5. 测试
curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: cg_***" \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "session_id": "test", "user_id": "alice"}'
```

## Features

| Feature | Status | Description |
|---------|--------|-------------|
| Auth + RBAC0 | ✅ | API Key 认证 + 4 角色权限模型 |
| Request Signature | ✅ | HMAC-SHA256 防重放签名 |
| Multi-tenant | ✅ | 租户隔离 + 数据行级隔离 |
| Audit Logging | ✅ | 全量审计 + CSV 导出 |
| LangGraph Pipeline | ✅ | 10 节点 DAG 管线 |
| LangFuse Tracing | ✅ | 全链路可观测 |
| Cache (Exact + Fingerprint) | ✅ | 精确匹配 + 意图指纹缓存 |
| Cost Management | ✅ | 预算控制 + 模型路由 |
| Skill Dual-path | ✅ | 短路径(50ms) + 长路径(LLM) |
| Security Guardrails | ✅ | 注入检测 + PII 脱敏 + 输出审查 |
| File Upload Hardening | ✅ | MIME 头检测 + UUID 重命名 |
| Circuit Breaker | ✅ | LLM 故障自动降级 |
| Health Check | ✅ | 深度健康检查 + SLA 指标 |
| Error Codes | ✅ | 结构化错误码统一响应 |
| LLM API Key Governance | ✅ | AES-256-GCM 加密 + 租户隔离 |
| Docker + CI/CD | ✅ | Multi-stage build + GitHub Actions |
| Playground | ✅ | 4-Tab 测试页面 |

## Comparison

|   | ContextGate | Dify | FastGPT |
|---|------------|------|---------|
| 架构 | LangGraph DAG | Workflow Builder | Workflow |
| 租户隔离 | ✅ 行级 + 审计 | ✅ | ❌ |
| 审计 | ✅ 全量 + 导出 | ❌ | ❌ |
| 签名认证 | ✅ HMAC-SHA256 | ❌ | ❌ |
| API Key 治理 | ✅ AES-256-GCM | ❌ | ❌ |
| 安全护栏 | ✅ 注入+PII+输出 | ⚠️ 基础 | ❌ |
| 可观测 | ✅ LangFuse | ✅ | ⚠️ |
| 定位 | 企业 LLM 网关 | 应用平台 | 知识库 |

## License

Apache 2.0 — see [LICENSE](LICENSE)
```

---

### 17.03: 社区文件

### 创建: `CONTRIBUTING.md`

```markdown
# Contributing to ContextGate

## PR Process

1. Fork the repository
2. Create a feature branch (`feat/`, `fix/`, `chore/`, `refactor/`)
3. Write tests for new code
4. Run `make lint && make typecheck && make test`
5. Submit PR with description

## Commit Convention

```
<type>: <description>

Signed-off-by: Your Name
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`

## DCO

All commits must include `Signed-off-by:` line.
```

### 创建: `SECURITY.md`

```markdown
# Security Policy

## Reporting a Vulnerability

Email: security@contextgate.dev
Response time: within 48 hours

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ |
| < 1.0   | ❌ |

## Security Measures

- AES-256-GCM for API Key encryption
- HMAC-SHA256 request signing
- Prompt injection detection
- PII redaction
- Rate limiting
- Circuit breaker
```

### 创建: `CODE_OF_CONDUCT.md`

```markdown
# Contributor Covenant Code of Conduct v2.1
```

### 创建: `CHANGELOG.md`

```markdown
# Changelog

## [1.0.0] - 2026-07-29

### Added
- Auth + RBAC0 with API Key authentication
- HMAC-SHA256 request signature anti-replay
- Multi-tenant isolation with audit logging
- LangGraph 10-node DAG pipeline
- LangFuse observability integration
- Exact + fingerprint cache system
- Cost management + model routing
- Skill dual-path (short path 50ms)
- Security guardrails (injection, PII, output)
- File upload hardening
- Circuit breaker + fallback
- Health check + SLA metrics
- Structured error codes
- LLM API Key governance (AES-256-GCM)
- Docker + CI/CD pipeline
- Seed data + mock scenarios
```

### 创建: `ROADMAP.md`

```markdown
# Roadmap

## v1.0 (Current)
- ✅ Complete plan: 18 tasks, 79 subtasks

## v1.1 (Next)
- [ ] RAG Deepening (HyDE + ReRank)
- [ ] SSE Streaming for chat
- [ ] Web Admin UI

## v2.0
- [ ] ai-platform integration
- [ ] Multi-region deployment
- [ ] A/B testing framework
```

---

### 17.04: 合规文档

### 创建: `docs/COMPLIANCE.md`

```markdown
# Compliance — 个保法合规

## Data Flow

```
用户输入 → guardrails_input(PII脱敏) → LLM(无PII) → guardrails_output → 用户
                                              ↓
                                        审计日志(含原始输入)
```

## Data Retention

- 审计日志: 180 天
- 对话记录: 不限制（可配置 TTL）
- 缓存: 5 分钟（精确） / 24 小时（指纹）

## Data Isolation

- 租户行级隔离: 所有查询 WHERE tenant_id=:tid
- 跨租户访问: 仅 super_admin / auditor 角色
- 审计导出: auditor 可导出，不包含对话内容
```

### 创建: `docs/SECURITY_AUDIT.md`

```markdown
# Security Audit — 深度防御 7 层模型

Layer 1: Network (nginx rate limit + HTTPS)
Layer 2: Auth (X-API-Key + HMAC signature)
Layer 3: RBAC (4 roles + permission check)
Layer 4: Guardrails (injection + PII + output)
Layer 5: Circuit Breaker (fault isolation)
Layer 6: Key Mgmt (AES-256-GCM encryption)
Layer 7: Audit (full audit trail)
```

### 创建: `docs/DEPLOYMENT.md`

部署 checklist 等内容。

### 创建: `docs/ARCHITECTURE.md`

```markdown
# Architecture

## Overview

ContextGate is an enterprise LLM gateway built on:
- FastAPI (API layer)
- LangGraph (pipeline orchestration)
- pgvector (vector storage)
- LangFuse (observability)

## Data Flow

See COMPLIANCE.md for data flow diagram.

## Component Diagram

```
[Client] → [nginx] → [FastAPI] → [LangGraph Pipeline]
    ↑                                  ↓
    |                           [pgvector DB]
    |                                  ↓
    |                           [LangFuse]
    └────←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
```

## Key Design Decisions

1. TypedDict over Pydantic for PipelineState — avoids serialization overhead
2. Harness pattern for all external calls — unified observability
3. AES-256-GCM for key encryption — authenticated encryption
4. Fire-and-forget audit logging — doesn't block main request
```

---

### 17.05: 质量门禁 + 开发壳子

### 创建: `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.0
    hooks:
      - id: mypy
        args: [--ignore-missing-imports, backend/]
```

### 创建: `.editorconfig`

```ini
root = true

[*]
indent_style = space
indent_size = 4
end_of_line = lf
charset = utf-8
trim_trailing_whitespace = true
insert_final_newline = true

[*.{yml,yaml,md,json,toml}]
indent_size = 2
```

### 创建: `.vscode/extensions.json`

```json
{
  "recommendations": [
    "charliermarsh.ruff",
    "matangover.mypy",
    "tamasfe.even-better-toml",
    "yzhang.markdown-all-in-one"
  ]
}
```

### 创建: `.vscode/settings.json`

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.analysis.typeCheckingMode": "basic",
  "[python]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.codeActionsOnSave": {
      "source.organizeImports.ruff": "explicit"
    }
  },
  "files.exclude": {
    "**/__pycache__": true,
    "**/.pytest_cache": true,
    "**/*.pyc": true
  }
}
```

---

### 17.06: Playground 测试页

### 创建: `frontend/playground.html`

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>ContextGate Playground</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
    .tabs { display: flex; background: #1e293b; border-bottom: 2px solid #334155; }
    .tab { padding: 12px 24px; cursor: pointer; border: none; background: transparent; color: #94a3b8; font-size: 14px; }
    .tab.active { color: #38bdf8; border-bottom: 2px solid #38bdf8; margin-bottom: -2px; }
    .panel { display: none; padding: 24px; }
    .panel.active { display: block; }
    textarea, input[type="text"], input[type="password"] { width: 100%; padding: 8px; border: 1px solid #334155; background: #1e293b; color: #e2e8f0; border-radius: 6px; font-size: 13px; }
    textarea { min-height: 80px; font-family: 'Courier New', monospace; }
    button { padding: 8px 16px; background: #38bdf8; color: #0f172a; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }
    button:hover { background: #7dd3fc; }
    pre { background: #1e293b; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 12px; max-height: 400px; overflow-y: auto; }
    .label { font-size: 12px; color: #94a3b8; margin-bottom: 4px; margin-top: 12px; }
    .row { display: flex; gap: 12px; }
    .col { flex: 1; }
  </style>
</head>
<body>
  <div class="tabs">
    <div class="tab active" onclick="switchTab(0)">💬 Chat</div>
    <div class="tab" onclick="switchTab(1)">🔑 Admin</div>
    <div class="tab" onclick="switchTab(2)">📋 Audit</div>
    <div class="tab" onclick="switchTab(3)">⚙️ System</div>
  </div>

  <div id="tab0" class="panel active">
    <div class="label">API Key</div>
    <input type="password" id="apiKey" placeholder="cg_...">
    <div class="row">
      <div class="col"><div class="label">Session ID</div><input type="text" id="sessionId" value="test"></div>
      <div class="col"><div class="label">User ID</div><input type="text" id="userId" value="alice"></div>
    </div>
    <div class="label">Message</div>
    <textarea id="message">你好，最近项目压力好大</textarea>
    <button onclick="sendChat()">Send</button>
    <h3 style="margin-top:16px;">Response</h3>
    <pre id="chatResponse">{}</pre>
  </div>

  <div id="tab1" class="panel">
    <h3>Create API Key</h3>
    <div class="row">
      <div class="col"><div class="label">User ID</div><input type="text" id="newUserId" value="testuser"></div>
      <div class="col"><div class="label">Role</div><input type="text" id="newRole" value="user"></div>
    </div>
    <button onclick="createApiKey()">Create</button>
    <h3 style="margin-top:16px;">Pending Requests</h3>
    <button onclick="listPending()">Refresh</button>
    <pre id="pendingResponse">[]</pre>
  </div>

  <div id="tab2" class="panel">
    <div class="row">
      <div class="col"><div class="label">Tenant</div><input type="text" id="auditTenant" value="acme"></div>
      <div class="col"><div class="label">Limit</div><input type="text" id="auditLimit" value="10"></div>
    </div>
    <button onclick="queryAudit()">Query</button>
    <pre id="auditResponse">[]</pre>
  </div>

  <div id="tab3" class="panel">
    <button onclick="healthCheck()">Health Check</button>
    <pre id="healthResponse">{}</pre>
    <h3 style="margin-top:16px;">cURL Generator</h3>
    <div class="label">API Key</div>
    <input type="text" id="curlKey" placeholder="cg_...">
    <button onclick="genCurl()">Generate</button>
    <pre id="curlOutput"># 点击 Generate 生成 curl 命令</pre>
  </div>

  <script>
    const BASE = '';

    function switchTab(i) {
      document.querySelectorAll('.tab').forEach((t, idx) => t.classList.toggle('active', idx === i));
      document.querySelectorAll('.panel').forEach((p, idx) => p.classList.toggle('active', idx === i));
    }

    async function api(path, opts = {}) {
      const key = document.getElementById('apiKey')?.value || document.getElementById('curlKey')?.value || '';
      const headers = { 'Content-Type': 'application/json', ...opts.headers };
      if (key) headers['X-API-Key'] = key;
      const res = await fetch(BASE + path, { ...opts, headers });
      const text = await res.text();
      try { return JSON.stringify(JSON.parse(text), null, 2); }
      catch { return text; }
    }

    async function sendChat() {
      const data = { message: document.getElementById('message').value, session_id: document.getElementById('sessionId').value, user_id: document.getElementById('userId').value };
      document.getElementById('chatResponse').textContent = await api('/chat', { method: 'POST', body: JSON.stringify(data) });
    }

    async function createApiKey() {
      const data = { user_id: document.getElementById('newUserId').value, role: document.getElementById('newRole').value };
      document.getElementById('pendingResponse').textContent = await api('/api/admin/api-keys', { method: 'POST', body: JSON.stringify(data) });
    }

    async function listPending() {
      document.getElementById('pendingResponse').textContent = await api('/api/admin/pending-requests');
    }

    async function queryAudit() {
      const tid = document.getElementById('auditTenant').value;
      const lim = document.getElementById('auditLimit').value;
      document.getElementById('auditResponse').textContent = await api(`/api/audit/logs?tenant_id=${tid}&limit=${lim}`);
    }

    async function healthCheck() {
      document.getElementById('healthResponse').textContent = await api('/health');
    }

    function genCurl() {
      const key = document.getElementById('curlKey').value || 'YOUR_API_KEY';
      document.getElementById('curlOutput').textContent =
`# Chat
curl -X POST ${BASE}/chat \\
  -H "X-API-Key: ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"message":"你好","session_id":"test","user_id":"alice"}'

# Health
curl ${BASE}/health

# Audit
curl ${BASE}/api/audit/logs?limit=5 \\
  -H "X-API-Key: ${key}"

# Create API Key
curl -X POST ${BASE}/api/admin/api-keys \\
  -H "X-API-Key: ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"user_id":"newuser","role":"user"}'`;
    }
  </script>
</body>
</html>
```

### 修改: `backend/app.py`

```python
# 添加 Playground 静态文件挂载
from fastapi.staticfiles import StaticFiles
from pathlib import Path

playground_dir = Path(__file__).parent.parent / "frontend"
if playground_dir.exists():
    app.mount("/playground", StaticFiles(
        directory=str(playground_dir), html=True
    ), name="playground")
```

---

### 17.07: 前端退役（可选 — 保留 frontend/playground.html）

```bash
# 不要删除 frontend/ 目录，playground.html 放在 frontend/ 下面
# 原有的 React 前端代码保留不动
```

> ⚠️ **Cursor 注意:** 不要删除 `frontend/src/` 或其他前端文件。playground.html 作为轻量测试客户端保留。

---

## B. Task 18: LLM API Key 安全治理

### 18.01: llm_api_keys 表 + 加密工具

### 文件: `backend/database/init_pgvector.sql`（追加）

```sql
-- ========== Task 18: LLM API Key 管理 ==========
CREATE TABLE IF NOT EXISTS llm_api_keys (
    id                SERIAL PRIMARY KEY,
    tenant_id         VARCHAR(64) NOT NULL,
    key_alias         VARCHAR(128) NOT NULL,
    provider          VARCHAR(32) NOT NULL,
    base_url          VARCHAR(256) NOT NULL DEFAULT '',
    encrypted_key     TEXT NOT NULL,
    key_version       INT NOT NULL DEFAULT 1,
    is_active         BOOLEAN NOT NULL DEFAULT true,
    expires_at        TIMESTAMPTZ,
    last_verified     TIMESTAMPTZ,
    last_verified_ok  BOOLEAN,
    description       TEXT DEFAULT '',
    created_by        VARCHAR(128) NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT now(),
    rotated_at        TIMESTAMPTZ,
    UNIQUE(tenant_id, key_alias)
);
CREATE INDEX IF NOT EXISTS idx_lak_tenant ON llm_api_keys(tenant_id, is_active);
```

### 创建: `backend/core/key_manager.py`

```python
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

import os
import base64
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
        """用旧 master key 解密，用新 key 重新加密（轮转用）"""
        plaintext = self.decrypt(encrypted_b64)
        old_master = os.environ.get("LLM_KEY_MASTER_KEY")
        try:
            os.environ["LLM_KEY_MASTER_KEY"] = new_master_key_hex
            new_mgr = KeyManager()
            return new_mgr.encrypt(plaintext)
        finally:
            os.environ["LLM_KEY_MASTER_KEY"] = old_master or ""
```

---

### 18.02: LLMKeyRepository

### 创建: `backend/core/key_repository.py`

```python
"""
LLM API Key 数据库读写层。

职责:
  - 按租户+provider 查询可用 key
  - 自动解密返回明文
  - LRU 缓存已解密 key
  - 支持 key 版本 / 过期检测
"""

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional
from sqlalchemy import text
from backend.core.key_manager import KeyManager
from backend.database.pgvector_session import get_pg_session


@dataclass
class LLMKey:
    id: str
    tenant_id: str
    provider: str
    base_url: str
    api_key: str        # 已解密明文
    key_version: int
    is_active: bool
    expires_at: Optional[int]  # Unix timestamp


class LLMKeyCache:
    """LRU 缓存，已解密 key 不进日志"""
    MAX = 100
    TTL_SEC = 300

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

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)


class LLMKeyRepository:
    """按租户+provider 获取 LLM API Key，自动解密"""

    def __init__(self, key_manager: KeyManager | None = None):
        self._km = key_manager or KeyManager()
        self._cache = LLMKeyCache()

    async def get_key(
        self, tenant_id: str, provider: str = "default"
    ) -> LLMKey | None:
        """查询: 租户专用 key → 全局默认 key"""
        cache_key = f"{tenant_id}:{provider}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        # 查数据库
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            # 优先租户级
            sql = text("""
                SELECT * FROM llm_api_keys
                WHERE tenant_id = :tid AND provider = :p AND is_active = true
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY key_version DESC LIMIT 1
            """)
            row = session.execute(sql, {"tid": tenant_id, "p": provider}).fetchone()

            # 全局兜底
            if not row:
                row = session.execute(sql, {"tid": "*", "p": provider}).fetchone()

            # Fallback
            if not row:
                from config import Config
                if Config.LLM_API_KEY_FALLBACK:
                    fallback = LLMKey(
                        id="fallback",
                        tenant_id=tenant_id,
                        provider=provider,
                        base_url=Config.LLM_BASE_URL_FALLBACK,
                        api_key=Config.LLM_API_KEY_FALLBACK,
                        key_version=0,
                        is_active=True,
                        expires_at=None,
                    )
                    return fallback
                return None

            plain_key = self._km.decrypt(row.encrypted_key)
            key_obj = LLMKey(
                id=str(row.id),
                tenant_id=row.tenant_id,
                provider=row.provider,
                base_url=row.base_url or "",
                api_key=plain_key,
                key_version=row.key_version,
                is_active=row.is_active,
                expires_at=int(row.expires_at.timestamp()) if row.expires_at else None,
            )
            self._cache.set(cache_key, key_obj)
            return key_obj

    def invalidate_cache(self, tenant_id: str, provider: str = "default") -> None:
        self._cache.invalidate(f"{tenant_id}:{provider}")
```

---

### 18.03: 改造 config.py

### 修改: `config.py`

```python
import os


class Config:
    # ── LLM API Key 安全治理 ──
    # 替代所有明文 key: LLM_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY
    # LLM Key 从 llm_api_keys 表加密存储，通过 KeyManager 运行时解密
    LLM_KEY_MASTER_KEY = os.getenv("LLM_KEY_MASTER_KEY", "")

    # ── 兼容层（迁移过渡期使用）──
    # DB 中无对应租户 key 时降级到旧 env 变量
    LLM_API_KEY_FALLBACK = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    LLM_BASE_URL_FALLBACK = os.getenv("LLM_BASE_URL") or os.getenv("API_BASE_URL", "https://api.deepseek.com")
```

> ⚠️ **Cursor 注意:** 搜索所有引用 `config.LLM_API_KEY` 的地方，替换为 `LLMKeyRepository.get_key()`。保留 `LLM_API_KEY_FALLBACK` 过渡。

---

### 18.04: 改造 model_router — 注入 tenant 级 key

### 取消 `backend/pipeline/nodes/model_router.py` 中的注释（取消 Task 5b 中注释掉的 LLM Key 注入代码）：

取消下面这段的注释：

```python
    # 注入 LLM API Key
    try:
        from backend.core.key_repository import LLMKeyRepository
        provider = _detect_provider(rule["model"])
        key_data = await LLMKeyRepository().get_key(state["tenant_id"], provider)
        if key_data:
            state["llm_api_key"] = key_data.api_key
            state["llm_base_url"] = key_data.base_url
            state["llm_key_id"] = key_data.id
            state["llm_key_version"] = key_data.key_version
    except ImportError:
        pass
```

---

### 18.05: Admin API — LLM Key 管理

### 追加到 `backend/routers/admin.py`

```python
# ── LLM API Key 管理 ──

from backend.core.key_manager import KeyManager
from backend.core.key_repository import LLMKeyRepository


class CreateLlmKeyRequest(BaseModel):
    tenant_id: str
    key_alias: str
    provider: str = "deepseek"
    base_url: str = ""
    api_key_plaintext: str
    expires_in_days: int | None = None
    description: str = ""


@router.post("/llm-keys")
async def create_llm_key(
    req: CreateLlmKeyRequest,
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """创建 LLM API Key（明文传入，加密存储）"""
    km = KeyManager()
    encrypted = km.encrypt(req.api_key_plaintext)

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            INSERT INTO llm_api_keys
                (tenant_id, key_alias, provider, base_url, encrypted_key,
                 description, created_by, expires_at)
            VALUES
                (:tid, :alias, :prov, :url, :enc,
                 :desc, :by, now() + interval '1 day' * :days)
            RETURNING id, created_at
        """)
        row = session.execute(sql, {
            "tid": req.tenant_id, "alias": req.key_alias,
            "prov": req.provider, "url": req.base_url,
            "enc": encrypted, "desc": req.description,
            "by": tenant.user_id,
            "days": req.expires_in_days or 365,
        }).fetchone()
        session.commit()

    return {"id": row.id, "key_alias": req.key_alias, "status": "created"}


@router.get("/llm-keys")
async def list_llm_keys(
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """列出租户 LLM Key（不返回明文）"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            SELECT id, tenant_id, key_alias, provider, base_url,
                   key_version, is_active, expires_at, last_verified_ok,
                   description, created_at, rotated_at
            FROM llm_api_keys
            WHERE tenant_id = :tid
            ORDER BY created_at DESC
        """)
        rows = session.execute(sql, {"tid": tenant.tenant_id}).fetchall()
    return [
        {
            "id": r.id, "tenant_id": r.tenant_id,
            "key_alias": r.key_alias, "provider": r.provider,
            "key_version": r.key_version, "is_active": r.is_active,
            "last_verified_ok": r.last_verified_ok,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.delete("/llm-keys/{key_id}")
async def delete_llm_key(
    key_id: int,
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """吊销 LLM Key"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("UPDATE llm_api_keys SET is_active=false WHERE id=:id")
        session.execute(sql, {"id": key_id})
        session.commit()
    return {"status": "deleted", "id": key_id}


@router.post("/llm-keys/{key_id}/verify")
async def verify_llm_key(
    key_id: int,
    tenant: TenantContext = Depends(require_permission("admin:llm_key")),
):
    """验证 Key 有效性"""
    from backend.core.key_health import verify_key_by_id
    result = await verify_key_by_id(key_id)
    return result
```

---

### 18.06: Key 健康检查

### 创建: `backend/core/key_health.py`

```python
"""LLM API Key 健康检查"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from backend.database.pgvector_session import get_pg_session
from backend.core.key_manager import KeyManager
from backend.core.key_repository import LLMKeyRepository


async def verify_key_by_id(key_id: int) -> dict:
    """验证单个 Key"""
    session_factory = get_pg_session()
    with session_factory.Session() as session:
        row = session.execute(
            text("SELECT * FROM llm_api_keys WHERE id = :id"),
            {"id": key_id},
        ).fetchone()
        if not row:
            return {"status": "not_found"}

    km = KeyManager()
    plain_key = km.decrypt(row.encrypted_key)

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=plain_key, base_url=row.base_url or None)
        await client.models.list()  # 轻量请求
        ok = True
    except Exception:
        ok = False

    # 更新检查结果
    with session_factory.Session() as session:
        session.execute(
            text("""
                UPDATE llm_api_keys
                SET last_verified = now(), last_verified_ok = :ok
                WHERE id = :id
            """),
            {"ok": ok, "id": key_id},
        )
        session.commit()

    return {"status": "ok" if ok else "failed", "key_id": key_id}


class KeyHealthChecker:
    """定时检查 LLM API Key 状态"""

    CHECK_INTERVAL = 3600  # 每小时

    async def run_periodic_check(self):
        """后台循环 — 注册到 FastAPI lifespan"""
        while True:
            await self._check_all()
            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _check_all(self):
        """查出需要检查的 key"""
        session_factory = get_pg_session()
        with session_factory.Session() as session:
            rows = session.execute(text("""
                SELECT id, encrypted_key, base_url FROM llm_api_keys
                WHERE is_active = true
                  AND (
                    expires_at IS NOT NULL AND expires_at < now() + interval '7 days'
                    OR last_verified IS NULL
                    OR last_verified < now() - interval '24 hours'
                  )
            """)).fetchall()

        for row in rows:
            await verify_key_by_id(row.id)
```

---

### 18.07: Seed 数据

### 追加到 `scripts/seed_pgvector.py`

```python
def seed_llm_keys():
    """写入初始 LLM API Key（从 env 迁移到数据库）"""
    import os
    from backend.core.key_manager import KeyManager

    env_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    if not env_key:
        print("  ⚠️  未找到 LLM_API_KEY 环境变量，跳过 seed LLM Key")
        return

    km = KeyManager()
    encrypted = km.encrypt(env_key)

    session_factory = get_pg_session()
    with session_factory.Session() as session:
        sql = text("""
            INSERT INTO llm_api_keys
                (tenant_id, key_alias, provider, base_url, encrypted_key,
                 description, created_by)
            VALUES
                ('*', 'default-env', 'deepseek', '', :enc,
                 '从环境变量迁移的默认 Key', 'seed_script')
            ON CONFLICT (tenant_id, key_alias) DO NOTHING
            RETURNING id
        """)
        row = session.execute(sql, {"enc": encrypted}).fetchone()
        session.commit()

    if row:
        print(f"  ✅ LLM API Key 已加密存储到数据库 (id={row.id})")
    else:
        print("  ℹ️  LLM API Key 已存在，跳过")
```

在主函数末尾调用 `seed_llm_keys()`。

---

## 验证

```bash
# Task 17 验证
head -5 LICENSE                    # → Apache License 2.0
ls CONTRIBUTING.md SECURITY.md     # → 存在
ls docs/COMPLIANCE.md docs/ARCHITECTURE.md  # → 存在
ls .editorconfig .vscode/extensions.json  # → 存在

# Task 18 验证 — 加密工具
uv run python -c "
from backend.core.key_manager import KeyManager
mgr = KeyManager(master_key='00' * 32)

# 加解密往返
original = 'sk-test-key-value'
encrypted = mgr.encrypt(original)
assert encrypted != original
decrypted = mgr.decrypt(encrypted)
assert decrypted == original
print('✅ KeyManager 加解密测试通过')

# 篡改检测
tampered = encrypted[:-5] + 'XXXXX' + encrypted[-5:]
try:
    mgr.decrypt(tampered)
    print('❌ 篡改未检测到！')
except Exception:
    print('✅ 篡改检测正常')

# 不同 nonce → 不同密文
e1 = mgr.encrypt('same')
e2 = mgr.encrypt('same')
assert e1 != e2
print('✅ Nonce 随机性验证通过')
"

# Task 18 验证 — KeyRepository
uv run python -c "
from backend.core.key_repository import LLMKeyRepository, LLMKeyCache
cache = LLMKeyCache()
cache.set('test', 'value')
print(f'✅ LLMKeyCache 基本功能: get={cache.get(\"test\")}')
"

# Task 18 验证 — 健康检查
uv run python -c "
from backend.core.key_health import KeyHealthChecker
print('✅ KeyHealthChecker 导入成功')
"

# Playground
ls frontend/playground.html        # → 存在
```
