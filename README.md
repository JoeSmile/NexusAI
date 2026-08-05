# NexusAI

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-green)]()
[![CI](https://github.com/joe/context-gate/actions/workflows/ci.yml/badge.svg)]()

> **The Governance Hub for Enterprise AI** — 企业 AI 中台

企业都有业务中台、数据中台,缺的是 AI 中台。NexusAI 补上这一层:**统一入口调企业 AI 能力,
能力由 IT 编排,数据接内部 OA/RAG,治理平台兜底。**

[简体中文](README.md) | [English](README.en.md)

## 定位

- **治理是卖点,不是功能。** 审计、预算、权限、合规——回答企业那一句「你的数据敢不敢给它」。
- **不做 agent 编排平台。** Dify/Coze 做应用编排,NexusAI 做治理——应用可以跑在 Dify,数据必须过 NexusAI。
- **不是再造一个中台。** 企业已有业务中台/数据中台,NexusAI 是给它们加 AI 治理层。

定位与五层架构的完整推导见 [`docs/strategy/AI_MIDDLE_PLATFORM.md`](docs/strategy/AI_MIDDLE_PLATFORM.md)(2026-08-05 拍板)。

## 架构(五层)

```
接入层      chat(意图识别)/ 工作台按钮(直连)/ API(X-API-Key + HMAC)
能力编排层   能力注册表 → 能力链(IT 编排)→ LangGraph DAG → 双路径(skill 直连 $0 / LLM)
数据连接层   OA / RAG 知识库 / 财务系统(租户+角色+行级隔离,数据不出域)
治理层       RBAC 4 角色 / 全量审计 / 预算配额 / 安全护栏 / 审批流
横切层       LangFuse 可观测 / 模型路由+harness / 缓存 / AES-256-GCM 密钥治理
```

技术底座是一条 LangGraph 有向无环图(管线节点):

```
auth_check → load_memory → rate_limiter → cache_check
  ├─ hit → END
  └─ miss → guardrails_input → analyze_parallel → build_context
            → model_router
              ├─ short path → execute skill → END (50ms, $0)
              └─ long path → llm_generate → guardrails_output
                            → write_memory + audit → END (1-5s)
```

## 快速开始

```bash
# 1. 启动基础设施(PostgreSQL + pgvector)
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
  -H "X-API-Key: *** \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "session_id": "test", "user_id": "alice"}'
```

### 测试前端(Task 30,推荐 QA 主入口)

```bash
uv run python scripts/seed_api_keys.py
uv run python scripts/seed_capabilities.py   # 能力链演示(可选)
uv run uvicorn backend.app:app --reload --port 8000
cd frontend && npm install && npm run dev    # http://localhost:5173
```

登录页支持**密码注册/登录**(Task 38)与 Key 登录(4 角色槽位,QA 角色切换用)。
右上角切换角色 → 对照 [`examples/qa/journeys/`](examples/qa/journeys/) 走面板。
详细步骤与面板说明见 [`frontend/README.md`](frontend/README.md)。

## 能力表

| 能力 | 状态 | 说明 |
|------|------|------|
| 统一入口:chat / 按钮 / API | 🚧 部分 | chat→能力链桥接在建(chat 现走 intent→skill,能力链走 invoke,两条路待打通) |
| 能力编排:注册表 + 能力链 | ✅ | 能力目录 + 权限绑定;链式编排(rag-ask → contract-query → vendor-risk) |
| 双路径执行 | ✅ | 意图置信度 ≥0.85 直连 skill(50ms, $0),否则走 LLM 管线 |
| RAG 知识库 | ✅ | pgvector + 上传 / 问答 / 检索 / 语义召回 |
| RBAC 4 角色 | ✅ | super_admin / tenant_admin / auditor / user |
| 全量审计 | ✅ | audit_logs + 合规导出(脱敏) |
| 预算配额 | ✅ | Task 32:单次 / 日 / 月三窗口限额 + 审批两本账 |
| 安全护栏 | ✅ | 注入检测 + PII 脱敏 + 输出审查 + 断路器 |
| 数据连接器(OA / 财务) | ⏳ 待建 | 第一阶段导入 + 定时同步起步 |
| 工作台按钮页 | ⏳ 待建 | 按钮 → 直连 invoke,业务用户一键执行 |

## 对比

|   | NexusAI | Dify | FastGPT |
|---|------------|------|---------|
| 定位 | 企业 AI 中台(治理 + 数据) | AI 应用编排平台 | 知识库问答 |
| 租户隔离 | ✅ 行级 + 审计 | ✅ | ❌ |
| 审计 | ✅ 全量 + 导出 | ❌ | ❌ |
| 签名认证 | ✅ HMAC-SHA256 | ❌ | ❌ |
| API Key 治理 | ✅ AES-256-GCM | ❌ | ❌ |
| 安全护栏 | ✅ 注入+PII+输出 | ⚠️ 基础 | ❌ |
| 可观测 | ✅ LangFuse | ✅ | ⚠️ |
| 企业数据(OA/RAG)连接 | ✅ RAG 内置,OA 规划 | ⚠️ | ❌ |

## 阶段

- **第一仗(现在):** 不做自助 workflow 编排。IT 配能力链,业务用户通过 chat 或工作台按钮调用。
- **V2 目标:** 自助编排(模板 + 表单式优先,拖拽画布后置)、审批节点(对账/采购流程要领导批)、样板场景(会计对账)。

## Docs

- [Strategy](docs/strategy/README.md) — 护城河 / 生存率 / 求职打法
- [AI 中台定位](docs/strategy/AI_MIDDLE_PLATFORM.md) — 一句话定位 + 五层架构(2026-08-05 拍板)
- [Architecture](docs/ARCHITECTURE.md)
- [Compliance](docs/COMPLIANCE.md)
- [Security Policy](docs/SECURITY.md)
- [Security Audit](docs/SECURITY_AUDIT.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Roadmap](docs/ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Code of Conduct](docs/CODE_OF_CONDUCT.md)

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE)
