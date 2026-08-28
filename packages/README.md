# packages/ — 领域库（模块化单体）

| 包 | 状态 | 原路径 |
|----|------|--------|
| intent | ✅ | `backend/modules/intent` |
| auth | ✅ 75.1 | `backend/core/auth` |
| pipeline | ✅ 75.2 | `backend/pipeline` |
| capability | ✅ 75.3 | `backend/core/capability` |
| plan / workflow | ✅ 75.4 | `backend/core/{plan,workflow}` |
| memory / guardrails / harness / skills | ✅ 75.6 | `backend/core/*` · `backend/skills` |
| org / social / billing / security / content_ops / skill_assets / tool_search / multimodal / terms / render / utils / ab | ✅ 75.8 | `backend/core/*` |

未搬：`backend/agent`（会话 Agent 运行时）· `backend/core` 散文件（errors、redis_tools…）· `backend/modules/intent` 仅 shim

另已迁 modules：`packages/{rag,llm,notification,channel,agent}`（75.9）

地图：[`docs/REPO_LAYOUT.md`](../docs/REPO_LAYOUT.md) · [`tasks/75-layout-packages-wave.md`](../tasks/75-layout-packages-wave.md)

