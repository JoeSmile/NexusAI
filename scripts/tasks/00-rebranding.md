# Task 00: Rebranding — ContextGate

> 全面改名为 **ContextGate**，作者改为 **Joe**。
> **前置依赖:** 无（第一个 Task）
> **完成后:** 执行 `tasks/01-pgvector-migration.md`

## Subtask 00.1: 项目元数据

**文件:** `pyproject.toml`
- `name`: `emotional-chat` → `context-gate`
- `description`: → `The Intelligent Gateway for LLM Context Management`
- `authors`: → `Joe`
- `keywords`: +`llm-gateway`, `context-management`, `observability`
- `urls`: 更新项目名

## Subtask 00.2: 后端代码脱敏

**文件:**
- `backend/app.py:95,96,209` — FastAPI title/description/root name
- `backend/routers/chat.py:27` — tag `聊天` → `chat`
- `backend/routers/memory.py` — tag `记忆` → `memory`
- `backend/routers/emotion_analysis.py` — tag `情感分析` → `analysis`
- `backend/routers/feedback.py` — tag `反馈` → `feedback`
- `backend/routers/agent.py` — tag `Agent` → `agent`
- `backend/modules/llm/core/llm_core.py` — `SimpleEmotionalChatEngine` → `ChatEngine`
- `backend/modules/llm/core/llm_with_plugins.py` — `EmotionalChatEngineWithPlugins` → `ChatEngineWithTools`
- `backend/xinyu_prompt.py` — 去掉所有"心语"字眼
- `config.py:13` — 去情感化

## Subtask 00.3: README 重写

**文件:** `README.md`, `README.en.md`
描述为通用 LLM 管线网关，去情感化。

## Subtask 00.4: Docker 配置改名

**文件:**
- `docker-compose.yml`, `docker-compose.local.yml` — service `backend` → `contextgate`
- `monitoring/prometheus.yml` — job_name → `contextgate`

## Subtask 00.5: 前端保留（开发期测试客户端）

- 不动 `frontend/` 任何文件
- 视为开发期测试客户端，部署/CI 不依赖前端
- README 保留 `http://localhost:3000`（注：v1.0 替换为 Playground）

## 验证

```bash
grep -r "心语\|情感陪伴" backend/ --include="*.py"     # → 0 匹配
grep "name.*=.*emotional-chat" pyproject.toml           # → 0 匹配
```
