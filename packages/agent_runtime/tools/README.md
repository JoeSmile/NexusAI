# Legacy Agent Tools（冻结 · Task 66）

> **状态:** legacy 冻结 — **不**注册进 `CapabilityRegistry`，不迁移进 Task 66 内置工具集。

| 文件 | 说明 |
|------|------|
| `calendar_api.py` | WaveS 心理陪伴遗留日历桩 |
| `scheduler_service.py` | 定时提醒桩 |
| `agent_tools.py` | 旧 Agent 工具函数（情绪趋势等） |

新工具统一在 `backend/core/capability/builtin/`（Task 66 切片 1）注册，调用走 `backend/core/capability/invoke.py` 治理链。

`backend/agent/tool_caller.py` 内本地 `ToolRegistry` 为遗留 Agent 路径，逐步收敛到 CapabilityRegistry。
