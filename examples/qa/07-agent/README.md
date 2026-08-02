# QA — Agent 模块

> 来源: `docs/MANUAL_TEST.md` §7。一键脚本: `./examples/qa/07-agent/agent_qa.sh`
> 页面: `http://localhost:8000/playground/agent.html`(BASE=/agent/)

## 用例

| # | 验证点 | 操作 | 预期 |
|---|--------|------|------|
| 7.1 | 多轮对话 | `POST /agent/chat` {user_id,message} | 有记忆的多轮回答 |
| 7.2 | 记忆读取 | `GET /agent/memory/{user_id}` | 返回该用户记忆 |
| 7.3 | 工具列表 | `GET /agent/tools` | 工具清单非空 |
| 7.4 | 回访 | `POST /agent/followup` {user_id} | 触发回访逻辑 |
| 7.5 | 历史 | `GET /agent/history/{user_id}` | 会话历史 |

## 一键

```bash
QA_KEY=<user key> ./examples/qa/07-agent/agent_qa.sh
```
