# Intent v8 评测数据（留底）

## 文件

| 文件 | 说明 |
|------|------|
| `intent_v8_manual_holdout.csv` | **手写 holdout**（59 条，8 类各 7–8 条），不来自训练池/golden 抽样 |
| `reports/intent_v8_eval_latest.json` | 最近一次 ML-only 评测明细（gold/pred/conf/tier） |
| `reports/intent_v8_eval_latest.md` | 人类可读摘要 |

## 标注原则

- 标签对齐 **Task 65 切片 8 产品 IntentType**（L0 8 类）
- 刻意避开 v8 训练语义迁移的歧义词（如「报销」→ after_sales、「周报」→ content_creation）
- **已知难例**（模型仍可能错，单独记录）见 `intent_v8_boundary_cases.csv`

## 运行

```bash
uv sync --extra intent-model
uv run python scripts/copy_intent_model.py --force   # 首次
uv run python scripts/eval_intent_model_v8.py
uv run pytest tests/test_intent_model_v8_accuracy.py -q
```

## 指标说明

- **Accuracy**：59 条 holdout 命中率
- **Macro F1**：8 类宏平均 F1
- **High-tier accuracy**：confidence ≥ 0.85 子集命中率（与线上短路径门禁同阈值）
