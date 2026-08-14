# Pilot B · 7A 金线旅程（Wave F）

> **执行:** `PERF=1 ./examples/qa/journeys/pilot_b_7a_gold_line.sh`  
> **前提:** `APP_ENV=dev` API 已起；建议 `LLM_PROVIDER=mock`  
> **证据:** `examples/qa/journeys/evidence/7a/`

## 剧本 10 步（可勾）

| # | 步骤 | 脚本对应 | 状态 |
|---|------|----------|------|
| 1 | seed 组织结构 | `03_org_unit` + memberships | ✅ |
| 2 | tenant_admin JWT → 建部门 + dept_manager | `01`/`04` | ✅ |
| 3 | 可见但 user 默认不可调、requestable 的 capability | `07` hang `kb:read` + seed | ✅ |
| 4 | user 登录；角标/需审批语义（API: requestable 节点） | `02`/`08` note + draft IR | ✅ |
| 5 | admin 发布 | `10_publish` | ✅ |
| 6 | user 运行 → suspended | `11`/`12`/`13` | ✅ |
| 7 | dept_manager 批准 → resume succeeded | `14`/`15`/`16` | ✅ |
| 8 | evidence 队列/节点证据 | `17_evidence_queue` | ✅（RAG miss 可空，已落盘） |
| 9 | auditor 导出：无明文密钥 | `18_audit_export` | ✅ |
| 10 | JWT/Bearer；无产品壳长期 cg_ | `19_jwt_not_apikey` | ✅ |

## 40.71 对照表

| 项 | 状态 | 注 |
|----|------|----|
| J0.5a JWT | ✅ | register→Bearer |
| J0.7 / J1.x 组织与权限 | ✅ | org + membership |
| S1–S5 挂起闸门 | ✅ | requestable hang 路径 |
| 乐观锁 publish | ✅ | `base_revision` |
| 证据队列 | ✅ | run nodes evidence JSON |
| 角标三态 | ✅ FE 人工 / API requestable | FE 目视补勾 |
| 审计导出 params 非明文 | ✅ | CSV 无 `cg_`/`sk-` |
| 并发 CAS / 429 | ✅ 单元 + Wave D/H | 本脚本 50 起步见下 |
| 性能冒烟 50 并发起步 | ✅ | **50/50 ok · ~1.86s**（`20_perf_smoke.json`） |
| 性能冒烟 1000 run 列表 &lt;2s | ✅ | seed 灌至 1000 后 10×100 页 **0.191s / 1000 items**（`api_page_max_100`）；证据 `20_perf_smoke.json` |
| 通知站内信 | 归 WaveE_2 | 7A 后补勾，不阻塞 |
| W6 Coze | skip | 旁路 |

## 5 分钟演示剧本（档 2）

1. **(30s)** 登录 tenant_admin → 组织树一眼看部门/成员  
2. **(60s)** 打开 workflow 编辑器 → 放 requestable 节点 → 发布  
3. **(60s)** 切 user 运行 → RunDetail 显示 suspended / hang  
4. **(60s)** 切审批人 `/approvals` → 批准 → run succeeded  
5. **(60s)** 打开证据 / auditor 导出 CSV 证明无明文密钥  

## 禁止项（本剧本未出现）

- 人带旧 key 期望 401（J0.5b）  
- 定时触发 / machine X-API-Key 主路径  
- 「发布后撤权」才挂起  

## 复跑

```bash
# API
APP_ENV=dev JWT_SECRET=dev-only-wave-a-jwt-secret-min-32b \
  LLM_PROVIDER=mock uv run python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000

# Journey
PERF=1 uv run python examples/qa/journeys/pilot_b_7a_gold_line.py
```


## Important 落档（2026-08-14）

| ID | 结论 |
|----|------|
| B1→A | seed ≥1000 `workflow_runs` 再测列表；诚实记录 page cap=100 + 耗时 |
| F2→B | `_load_key_chain_sync` 不补 sync DB；约定 async 只经 `to_thread`/harness（见 `llm_client` docstring + BACKLOG D6） |
| F3→A | `stream` 整段占槽保持（见 `llm_concurrency` 模块 docstring） |
