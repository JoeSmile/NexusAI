# QA — 评测

> 来源: `docs/MANUAL_TEST.md` §9。一键脚本: `./examples/qa/09-eval/eval_qa.sh`

## 用例

| # | 验证点 | 操作 | 预期 |
|---|--------|------|------|
| 9.1 | 单条评测 | `POST /evaluation/evaluate` {user_message,bot_response} | 返回评分+理由 |
| 9.2 | 批量 | `POST /evaluation/batch` {limit} | 多条结果 |
| 9.3 | 对比 | `POST /evaluation/compare-prompts` {user_message,responses} | 同请求多 prompt 对比表 |
| 9.4 | 统计 | `GET /evaluation/statistics` | 聚合数字与明细一致 |

## 一键

```bash
QA_KEY=<user key> ./examples/qa/09-eval/eval_qa.sh
```
