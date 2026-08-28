# packages/ — 领域库（模块化单体）

迁入完成（Task 75）；**shim 已删（75.7b）**。主路径一律 `from packages.<domain> ...`。

| 包 | 说明 |
|----|------|
| intent / auth / pipeline / capability / plan / workflow | 核心域 |
| memory / guardrails / harness / skills | 记忆与护栏 |
| org / social / billing / security / content_ops / skill_assets / tool_search / multimodal / terms / render / utils / ab | 业务域 |
| rag / llm / notification / channel / agent | 原 `backend/modules/*`（agent=MCP protocol） |
| **agent_runtime** | 原 `backend/agent` 会话运行时（AgentCore / MemoryHub） |

进程入口见 `apps/`。未搬：`backend/core` 散文件（errors、redis_tools…）。

地图：[`docs/REPO_LAYOUT.md`](../docs/REPO_LAYOUT.md)
