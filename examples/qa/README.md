# QA — 人工测试用例索引

> 按大类独立成册: 每个文件夹 = 用例清单(README.md)+ 可跑脚本(能自动化的部分)。
> 总纲(回归基线/缺陷表/Demo)仍在 `docs/MANUAL_TEST.md`。
> 原则: 不靠自述,一切以实机 curl / 页面操作结果为准;发现的缺口记入 MANUAL_TEST §13。

| 大类 | 页面 | 用例 | 一键脚本 |
|------|------|------|---------|
| 01-smoke — 冒烟 | — | README(1.1-1.5) | `01-smoke/smoke_qa.sh` |
| 02-auth — 认证权限矩阵 | playground.html | README(5 端点×4 角色) | `02-auth/auth_matrix_qa.sh` |
| 03-chat — Chat 管线 | playground.html | README(3.1-3.7) | `03-chat/chat_pipeline_qa.sh` |
| 04-sse — SSE 流式 | streaming.html | README(4.1-4.6,页面操作) | — |
| 05-intent — 意图识别 | intent.html | README(5.1-5.5) | `05-intent/intent_qa.sh` |
| 06-rag — RAG 知识库 | rag.html | README(6.1-6.17) | `../../scripts/rag_cache_qa.sh` |
| 07-agent — Agent | agent.html | README(7.1-7.5) | `07-agent/agent_qa.sh` |
| 08-admin — Admin 管理 | admin.html | README(8.1-8.6) | `08-admin/admin_qa.sh` |
| 09-eval — 评测 | eval.html | README(9.1-9.4) | `09-eval/eval_qa.sh` |
| 10-obs — 可观测 | LangFuse/Prometheus | README(10.1-10.8) | `10-obs/obs_qa.sh`(部分) |
| 11-sec — 安全专项 | — | README(11.1-11.7) | `11-sec/security_qa.sh`(11.7 手动) |
| 12-demo — Demo 剧本 | 全链路 | README(8 步) | — |
| journeys — 角色旅程 | 4 角色 | 4 份任务驱动剧本(分角色验证可用性) | 见各剧本 |

> **LangFuse 配合 QA 查看指南: [LANGFUSE.md](LANGFUSE.md)** —— 哪些 QA 能配合看、指标含义、
> 何时要优化、error 含义、深入排查路径(含 GAP-08 已知问题)。

## 常用 key 环境变量约定

| 变量 | 角色 |
|------|------|
| `QA_KEY` / `RAG_QA_KEY` | user(大多数脚本) |
| `QA_USER_KEY` | user(矩阵/冒烟用) |
| `QA_TADMIN_KEY` | tenant_admin |
| `QA_AUDITOR_KEY` | auditor |
| `QA_SUPER_KEY` | super_admin |
