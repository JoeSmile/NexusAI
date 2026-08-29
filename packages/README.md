# packages/ — 领域库（模块化单体）

迁入完成（Task 75）；**shim 已删（75.7b）**。主路径一律 `from packages.<domain> ...`。

| 包 | 说明 |
|----|------|
| intent / auth / pipeline / capability / plan / workflow | 核心域 |
| memory / guardrails / harness / skills | 记忆与护栏 |
| org / social / billing / security / content_ops / skill_assets / tool_search / multimodal / terms / render / utils / ab | 业务域 |
| rag / llm / notification / channel / agent | 原 `backend/modules/*`（agent=MCP protocol） |
| **agent_runtime** | 原 `backend/agent` 会话运行时（AgentCore / MemoryHub） |

进程入口见 `apps/`。`backend/` 仅余 `core/__init__.py` re-export。配置真源：根 `config.py`；异常真源：`packages.errors`（跟进 [`docs/backlog/E1-legacy-exception-cleanup.md`](../docs/backlog/E1-legacy-exception-cleanup.md)）。已迁对照见 [`docs/REPO_LAYOUT.md`](../docs/REPO_LAYOUT.md)。

地图：[`docs/REPO_LAYOUT.md`](../docs/REPO_LAYOUT.md)
