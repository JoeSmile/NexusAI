# Task 17: 项目占领 / Project Ownership

> 从"代码能跑"到"项目属于你"的最后一步。
> **前置依赖:** 除 Task 08/13 外全部完成
> **完成后:** ContextGate v1.0 发布 🚀

## Subtask 17.01: 法律护城河

- 创建: `LICENSE` — Apache 2.0（标准模板，年份 2026，作者 Joe）
- 修改: `.gitignore` — `chroma_db/`, `uploads/`, `data/`, `*.env`, `.venv/`
- 创建: `NOTICE` — 引用原 emotional_chat MIT 代码的版权声明

## Subtask 17.02: README 门面级重写

**修改:** `README.md`

结构:
```markdown
# ContextGate
[License Badge] [Python Badge] [CI Badge]

> The Intelligent Gateway for LLM Context Management

## Architecture [管线图]

## Quick Start (3 steps)
1. docker compose up
2. uv run scripts/seed_api_keys.py
3. curl -H "X-API-Key: $KEY" ...

## Features [功能矩阵表]

## Comparison [vs Dify / FastGPT 对比表]

## License: Apache 2.0
```

## Subtask 17.03: 社区文件

- 创建: `CONTRIBUTING.md` — PR 流程 + Conventional Commits + DCO
- 创建: `SECURITY.md` — 漏洞报告邮箱 + 48h 响应
- 创建: `CODE_OF_CONDUCT.md` — [Contributor Covenant v2.1](https://www.contributor-covenant.org/)
- 创建: `CHANGELOG.md` — Keep a Changelog 格式, v1.0.0 起
- 创建: `ROADMAP.md`
  - v1.0: 当前 Plan 全部完成
  - v1.1: RAG 深化（HyDE + ReRank）
  - v1.2: Web UI 管理后台
  - v2.0: ai-platform 集成

## Subtask 17.04: 合规文档

- 创建: `docs/COMPLIANCE.md`
  - 个保法合规：PII 脱敏位置、审计留存周期（180天）、数据隔离方案
  - 数据流向图：input → guardrails(PII) → LLM → guardrails(output) → user
- 创建: `docs/SECURITY_AUDIT.md`
  - 安全深度防御 7 层模型 + 渗透测试 checklist
- 创建: `docs/DEPLOYMENT.md`
  - 生产部署 checklist（改密码→HTTPS→环境变量→监控）
  - 最小资源 2C4G + 扩容方案
- 创建: `docs/ARCHITECTURE.md`
  - 架构图 + 数据流图 + 部署拓扑 + 组件说明

## Subtask 17.05: 质量门禁

- 创建: `.pre-commit-config.yaml`
  ```yaml
  repos:
    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.6.0
      hooks: [{id: ruff}, {id: ruff-format}]
    - repo: https://github.com/pre-commit/mirrors-mypy
      rev: v1.11.0
      hooks: [{id: mypy}]
  ```
- 创建: `.github/pull_request_template.md` — PR 模板
- 修改: `ci.yml` — 加 `--cov-fail-under=70`

## Subtask 17.06: Playground 测试页

**创建:** `frontend/playground.html`
- 4 个 Tab（纯 JS, 零依赖）:
  - **Chat**: API Key + message + session, Send, JSON 响应（含 trace_id）
  - **Admin**: 创建 API Key、待审批列表、审批
  - **Audit**: 按 tenant/时间查日志、导出 CSV
  - **System**: 健康检查、Metrics、curl 命令生成器
- **修改:** `backend/app.py` — `app.mount("/playground", StaticFiles(directory="frontend"))`

## Subtask 17.07: 前端退役

- 删除: `frontend/src/`, `frontend/public/`（保留 playground.html）
- 删除: `frontend/package.json`, `package-lock.json`
- 删除: `frontend/start_frontend.sh`, `stop_frontend.sh`
- 修改: `main.py` — 去掉前端启动逻辑
- 修改: `README.md` — `npm start` → `open http://localhost:8000/playground`
- 修改: `docker-compose*.yml` — 去掉前端相关端口

## Subtask 17.08: 开发壳子 / Dev Shell

> 一套舒服的开发环境配置，让 Cursor/VSCode 开箱即用。

**文件:**

| 文件 | 作用 |
|------|------|
| `.editorconfig` | 跨编辑器缩进/编码/换行统一 |
| `.vscode/extensions.json` | 推荐插件（Ruff, mypy, TOML, Markdown） |
| `.vscode/settings.json` | 自动 formatOnSave、lint 配置、文件排除 |
| `AGENTS.md` | AI Agent 项目上下文（架构/命令/规范），Cursor/Claude Code 自动读取 |
| `.gitignore` | 补充 chroma_db/, uploads/, data/, *.env, .venv/ |

**Skills 集成（Hermes Agent 用户使用）:**

在对话中加载以下 skill 获得项目上下文:
```bash
# 加载 code-review skill 做代码审查
skill_view(name='code-review')

# 加载 hermes-agent skill 做 Hermes 配置
skill_view(name='hermes-agent')
```

**AGENTS.md 内容结构:**
- 项目简介 + 技术栈
- 常用命令（uv sync, ruff, mypy, pytest）
- 架构简述 + 管线图
- 权限模型
- 目录约定
- 提交规范（Conventional Commits + DCO）

**验证:**
```bash
ls .editorconfig .vscode/extensions.json .vscode/settings.json AGENTS.md
# → 4 个文件都存在

grep "Signed-off-by" AGENTS.md
# → 有 DCO 说明
```

## 验证

```bash
head -5 LICENSE                  # → Apache License 2.0
ls CONTRIBUTING.md SECURITY.md   # → 存在
ls docs/COMPLIANCE.md docs/ARCHITECTURE.md  # → 存在
pre-commit run --all-files       # → 通过
open http://localhost:8000/playground  # → 4 个 Tab
```
