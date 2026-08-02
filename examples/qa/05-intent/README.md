# QA — 意图识别 [T20]

> 来源: `docs/MANUAL_TEST.md` §5。一键脚本: `./examples/qa/05-intent/intent_qa.sh`

## 用例

| # | 验证点 | 操作 | 预期 |
|---|--------|------|------|
| 5.1 | 类型列表 | `GET /intent/types` | 返回意图枚举,不含情感域意图 |
| 5.2 | 企业问题命中 [T20] | `GET /intent/detect?text=如何查询公司的信息安全管理制度` | intent=knowledge_query(或 rag 类),**不得兜进 advice**;confidence ≥0.7 |
| 5.3 | 规则兜底 | 报销流程/请假制度/设备报修各 3-5 条 | 全部命中合理意图,无 advice 残留 |
| 5.4 | analyze 全量 | `POST /intent/analyze` {text} | 意图+置信度+路由建议 |
| 5.5 | 文案残留 | `grep -rn "睡不着\|失眠\|难过" backend/` | 0 命中 [T20] |

## 一键

```bash
QA_KEY=<user key> ./examples/qa/05-intent/intent_qa.sh
```
