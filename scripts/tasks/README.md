# ContextGate — 改造计划

> **项目:** ContextGate
> **标语:** The Intelligent Gateway for LLM Context Management
> **源项目:** emotional_chat (心语情感陪伴机器人)
> **作者:** Joe
> **包管理:** uv
> **目标:** 将 emotional_chat demo 改造为可观测、可审计、可扩展、安全的企业级 LLM 前置处理管线

---

## 架构总览

```
用户 → FastAPI → LangGraph StateGraph → pgvector → LangFuse
                                                ↑
                        Auth(RBAC0) → Guardrails → Prometheus
```

### 管线图

```
[START] → auth_check → load_memory → rate_limiter → cache_check
  ├── [hit] ──► [END]
  └── [miss] ──► guardrails_input → analyze_parallel(并行)
                  → build_context → model_router
                    ├── [short] execute skill → [END]
                    └── [long] llm_generate → guardrails_output
                            → write_memory + audit → [END]
```

### 19 个 Task · 89 个 Subtask

| # | Task | Subtask 数 | 领域 |
|---|------|-----------|------|
| 00 | Rebranding — ContextGate | 5 | 基建 |
| 01 | pgvector 迁移 | 5 | 存储 |
| 02 | 认证 + RBAC0 + 审批 + **请求签名** | 6 | 安全 |
| 03 | 多租户 + 审计日志 | 4 | 企业 |
| 04 | LangGraph 管线重构 | 10 | 核心 |
| 05 | LangFuse 可观测性 | 3 | 观测 |
| 06 | 缓存系统（精确+指纹） | 3 | 性能 |
| 07 | 成本治理 + 模型路由 + Skill | 6 | 成本 |
| 08 | 依赖锁定 | 1 | 基建 |
| 09 | 安全护栏 | 3 | 安全 |
| 10 | 文件上传加固 | 2 | 安全 |
| 11 | 断路器 + 降级 | 3 | 韧性 |
| 12 | 健康检查 + SLA + 错误码 | 3 | 运维 |
| 13 | Seed 数据 + Mock 剧本 | 3 | 测试 |
| 14 | Docker + uv 最终化 | 4 | 部署 |
| 15 | CI/CD | 3 | 工程 |
| 16 | 生产部署 | 2 | 部署 |
| 17 | 项目占领 / Ownership | 7 | 社区 |
| **18** | **LLM API Key 安全治理** | **7** | **安全** |
| **19** | **性能瓶颈消除** | **10** | **性能** |

### 权限模型（RBAC0 + 应用级）

4 种角色:
- **super_admin** — 跨租户管理，`admin:*`
- **auditor** — 跨租户只读审计，`audit:read`, `audit:export`
- **tenant_admin** — 本租户管理，`chat:*`, `kb:*`, `admin:approve`
- **user** — 应用级权限挂载

Permission = `{resource}:{action}`
认证: `X-API-Key` Header → SHA256 hash → `api_keys` 表

### Mock 策略

| 组件 | 方式 |
|------|------|
| 主 LLM | **不 Mock**，走真实 API |
| Embedding | `np.random.randn(1536)` |
| 情绪/意图分析 | 直接调大模型 JSON 输出 |
| 记忆提取 | 预设 5 组 YAML 剧本 |

### 执行顺序

``` 00 → 01 → 02 → 03 → 04(最大) → 05 06 07(可并行) → 08 → 09 10 11 12(可并行) → 13 → 14 → 15 16(可并行) → 17 18(最后，18 依赖 02+03+04+07) → 19(建议 Batch 4 前先做 19.01~19.03 得基准线，其余 Batch 5 阶段并行) ```

每个 Subtask 5-10 分钟，完成后 git commit。
任务文件在 `tasks/` 目录下，每个文件包含完整描述、代码骨架和验证命令。
