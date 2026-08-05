# NexusAI 技术文章规划

> 一边写代码，一边沉淀文章。每个 Phaes 完成一批。

---

## v1.0 — 核心管线（当前 Phase）

### 管线架构

| # | 标题 | 核心内容 | 对应 Task |
|---|------|---------|-----------|
| 1 | **LangGraph 实战：11 个节点搭建企业级 LLM 管线** | PipelineState 设计、节点拆分原则、条件边实现、并行节点（asyncio.gather）、图编译与 FastAPI 转接层 | 04 |
| 2 | **Harness 模式：统一可观测的通用调用 wrapper** | pre/execute/post 三阶段抽象、断路器 + 重试退避 + 超时控制、LLMHarness 子类扩展（token 计数 + 成本计算）、Skill/Tool/MCP 重用同一管道 | 07 |
| 3 | **SSE Streaming 在 LangGraph 管线中的实践** | 短路径 vs 长路径的路由、ainvoke_until 部分执行、streaming 与非阻塞后处理（write_memory + audit）、LangFuse generation 追踪与 streaming 的共存 | 02 |

### 安全

| # | 标题 | 核心内容 | 对应 Task |
|---|------|---------|-----------|
| 4 | **从 7 层安全架构看企业 AI 网关设计** | 认证→限流→注入检测→PII 脱敏→二级权限→输出审查→断路器，每层的设计取舍、绕过攻击面分析、为什么要 7 层而不是 3 层 | 02, 09, 10, 11 |
| 5 | **多轮对话角色保真三要素** | 前置锚定（SYSTEM prompt 预留 token）、间隔强化（每 N 轮插入）、输出拦截（角色漂移正则检测）、token budget 分配策略 | 04, 09 |
| 6 | **API Key 治理：异常检测 + 自动故障切换** | Provider Key 多 key 轮换、连续错误自动停用、消费异常检测（凌晨高频/多 IP/消耗突增）、审计告警链路 | 07 |
| 7 | **Prompt 注入检测实战：规则引擎的取舍** | 注入模式库构建、误杀率 vs 漏报率权衡、log-only 模式调试期策略、规则更新不重启服务方案 | 09 |
| 8 | **PII 脱敏在企业合规中的落地姿势** | 手机/身份证/银行卡正则库、脱敏 vs 屏蔽 vs 拦截的三种策略、审计日志存原始数据（合规要求）、个保法对应条款 | 09 |

### 可观测

| # | 标题 | 核心内容 | 对应 Task |
|---|------|---------|-----------|
| 9 | **全链路可观测：LangFuse 在 LLM 管线中的集成实践** | trace 结构设计（chat_{tenant}/{session}）、每个 span 的语义（metrics/tokens/cost）、generation 级别的 prompt/response 记录、FastAPI + LangGraph + LangFuse 三层集成 | 05 |
| 10 | **结构化错误码设计：从 500 字符串到 {code, message, trace_id}** | ErrorCode 枚举分类、错误码与 HTTP 状态码的映射、trace_id 贯穿全链路、前端/CLI 统一错误处理 | 12 |

### 权限

| # | 标题 | 核心内容 | 对应 Task |
|---|------|---------|-----------|
| 11 | **RBAC0 + 应用级权限：企业 AI 平台的权限模型设计** | 四角色（super_admin/auditor/tenant_admin/user）、Permission = resource:action 设计、应用级权限挂载机制、FastAPI Depends 工厂模式实现 require_permission | 02 |
| 12 | **审批流程在 AI 网关中的设计** | approval_requests 表设计、高风险操作的异步审批模式、超时自动拒绝、审批通过后自动重试（或手动触发） | 02, 07 |

### 性能

| # | 标题 | 核心内容 | 对应 Task |
|---|------|---------|-----------|
| 13 | **意图指纹缓存：让你的 LLM 网关学会"记住"** | 精确缓存 vs 指纹缓存、意图指纹生成（intent + 归一化实体）、hash 策略（sha256）、跨用户复用 vs 隔离策略 | 06 |
| 14 | **emoji 归一化：情绪识别中丢失的那 30% 信号** | emoji→文字标签映射、对话轮次中情绪信号传递、对 analyze_parallel 节点的精度提升验证 | 04 |

### 工程

| # | 标题 | 核心内容 | 对应 Task |
|---|------|---------|-----------|
| 15 | **uv 迁移实战：从 pip 到 uv 的平滑过渡** | pyproject.toml 单源管理、uv sync/lock/run 工作流、GitHub Actions 中的 uv setup 配置、Docker multi-stage 构建 | 14, 15 |
| 16 | **为什么你的 LLM 网关不需要 BFF 层** | BFF 的适用场景（多端协议适配）、LLM 场景的瓶颈分析（SSE 统一的可行性）、NexusAI 作为自包含网关的设计 | 02 |

### 架构

| # | 标题 | 核心内容 | 对应 Task |
|---|------|---------|-----------|
| 17 | **pgvector 迁移：从 MySQL + ChromaDB 到 PostgreSQL 的存储统一** | Vector(1536) 类型配置、IVFFlat 索引调参、cosine_distance 算子、SQLAlchemy 集成、数据迁移策略（demo 无痛迁移） | 01 |
| 18 | **项目占领：开源项目从代码到社区的 7 层要素** | LICENSE（Apache 2.0 vs MIT）、社区文件（CONTRIBUTING/SECURITY/CODE_OF_CONDUCT）、合规文档（国企场景）、质量门禁（pre-commit + coverage）、README 门面设计 | 17 |

---

## v1.1 — RAG 深化

| # | 标题 | 核心内容 |
|---|------|---------|
| 19 | **多路召回融合：pgvector + Neo4j + 全文搜索** | BaseRetriever 抽象设计、Reciprocal Rank Fusion 实现、不同检索源的延迟/精度对比 |
| 20 | **威胁情报驱动的 API Key 自动拉黑** | 三级响应模型（SUSPICIOUS/WATCHED/BLOCKED）、记分板设计、auth_check 集成、误杀回退策略 |
| 21 | **RAG 评估体系的搭建与回归门禁** | 黄金测试集设计、Recall/Precision/MRR/Latency 指标、CI 中自动评估、精度下降门禁 |
| 22 | **HyDE + ReRank：检索增强的工业级实践** | HyDE 的 token 成本 vs 收益分析、本地 bge-reranker 部署、LLM 重排序的适用边界 |

---

## v2.0 — ai-platform 集成

| # | 标题 | 核心内容 |
|---|------|---------|
| 23 | **ai-platform：从 LLM 网关到 AI 治理平台** | 管理面 / 运行面分层设计、Pipeline 注册 API、可观测数据回传接口 |
| 24 | **企业级 AI 平台的多租户权限设计** | RBAC0 扩展为 RBAC + 应用级 + 资源级、审批流自动化、审计合规一体化 |

---

## 发布计划

```
v1.0 完成 → 发 18 篇文章（一篇文章 2-3 天）
            集中发到 掘金 / 知乎 / 公众号 / 推特

v1.1 完成 → 发 4 篇文章

v2.0 完成 → 发 2 篇文章
```

第一篇推荐从 **《从 7 层安全架构看企业 AI 网关设计》**（文章 #4）或 **《LangGraph 实战》**（文章 #1）开始——覆盖面广、面试能讲、技术深度够。
