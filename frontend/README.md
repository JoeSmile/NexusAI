# NexusAI 测试前端（Task 30）

Vite + React 19 测试控制台：同一界面填入 **4 角色 API Key**，用右上角角色切换器切换，对照 `examples/qa/journeys/` 剧本做联调。**不是**产品 FE（产品形态见 30.29）。

## 从零启动

```bash
# 仓库根目录
docker compose -f docker-compose.local.yml up -d   # 或 make up
uv sync
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_pgvector.py
uv run python scripts/seed_capabilities.py         # Agent 嵌套演示（可选）

# 终端 1 — API
uv run uvicorn backend.app:app --reload --port 8000

# 终端 2 — 测试 FE
cd frontend && pnpm install && pnpm run dev
# → http://localhost:5173
```

`vite.config.ts` 已把 `/api`、`/chat`、`/agent`、`/evaluation`、`/performance`、`/health` 等代理到 `localhost:8000`。

## 4 角色 Key 配置

1. 打开登录页，为 `user` / `tenant_admin` / `auditor` / `super_admin` 分别粘贴 seed 输出的 `cg_…` Key（明文仅显示一次，存在 **sessionStorage**，四槽互不覆盖）。
2. 右上角 **角色切换器** 切换激活槽位；面板会因 `roleEpoch` 自动刷新。
3. 无权限接口返回 403 时，页面红字高亮「该角色无权限（需 …）」— 换角色重试即可。

| 角色 | 典型用途 |
|------|----------|
| user | Chat / RAG / Agent Hub invoke |
| tenant_admin | Admin pending / llm-keys（无 `admin:*` 时 api-keys 可能分 tab 403） |
| auditor | Audit 列表 + CSV 导出 |
| super_admin | 全量 Admin api-keys |

## 面板对照 journeys

| 面板 | 路径 | journeys 线索 |
|------|------|----------------|
| Chat | `/panels/chat` | 用户对话 / 流式 |
| RAG | `/panels/rag` | 同问两次看 `cache_hit` |
| Admin | `/panels/admin` | 审批 / 建 key |
| Audit | `/panels/audit` | 审计导出 |
| Agent | `/panels/agent` | `vendor-risk-agent` 嵌套链 |
| Capabilities | `/panels/capabilities` | kind 徽章 / 可见性 |
| Eval / Performance | `/panels/eval` · `/panels/performance` | 评估与基准 |

剧本目录：[`examples/qa/journeys/`](../examples/qa/journeys/)。QA 主入口迁到本测试 FE；`examples/*.html` 仍由后端 `/playground/` 挂载，保留不删。

## 常用命令

```bash
cd frontend
pnpm run test    # vitest
pnpm run build   # tsc + vite build
pnpm run dev
```
