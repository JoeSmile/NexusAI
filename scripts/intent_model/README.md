# 意图识别模型：训练与数据飞轮

> 8 类业务意图分类器（BERT 微调）——L0 入口意图识别的模型侧。
> 模型产物：`data/models/intent_model_v8/`（训练输出，data/ 不入库）· 数据：`data/intent/`（train_pool_v8.jsonl / golden_v8.csv）

## 使用的模型

- **基座**：`bert-base-chinese`（110M 参数，encoder-only 分类模型）
- **类别**：8 类业务意图——greeting / pre_sales / after_sales / content_creation / content_analysis / knowledge_query / function / conversation
- **指标**：Test F1 macro 0.99 / Golden 冻结集命中率 98.8%（564 条）
- **推理**：CPU 5-15ms，无 GPU 依赖；生产接入 `backend/modules/intent/`（模型缺失自动降级规则引擎）

## 准备基座模型（国内网络走镜像）

```bash
mkdir -p data/models/bert-base-chinese
cd data/models/bert-base-chinese
for f in config.json tokenizer_config.json vocab.txt model.safetensors; do
  curl -L --retry 5 -o "$f" "https://hf-mirror.com/google-bert/bert-base-chinese/resolve/main/$f"
done
```

## 训练（需 GPU 或 CPU，torch 需 CUDA 版）

```bash
# ① 数据管线：重映射 + 合成 + golden 冻结集 → data/intent/train_pool_v8.jsonl / golden_v8.csv
uv run python scripts/intent_model/prepare_v8.py

# ② 训练：8:1:1 分层 + 类别加权 + 早停 + MLflow 追踪 → data/models/intent_model_v8/
uv run python scripts/intent_model/train_v8.py

# ③ 冻结集回归验证（模型没见过的数据）
uv run python scripts/intent_model/predict_v8.py --eval-golden

# ④ 单条预测（三档置信度）
uv run python scripts/intent_model/predict_v8.py "你们产品支持私有化部署吗"
# → pred: pre_sales (conf=0.99, tier=high)
```

实验追踪：`data/mlflow.db`（`mlflow ui` 查看每次训练的 params/metrics/混淆矩阵）。

## 数据飞轮（上线后启用）

**目标：降低模板合成占比（现 ~70%），用真实数据驱动重训。**

```
每日: 线上采集（audit intent 字段）→ 去重 → 规则高置信→弱标签自动入池 / 低置信→人工队列
每周: 人工标注 → 合并 → golden 回归(≥98.8% 不掉) → shadow A/B → 上线
```

- **重训触发条件（写死）**：真实样本增量 ≥500 条，或线上低置信率 >15%——不满足不动
- **门禁**：golden 回归 + shadow 分布一致性，双闸缺一不放行
- **版本管理**：重训 = 新版本（归档 data/models/intent_model_vX/），golden 通过才发布
- **数据质量增强（规划）**：结合 langfuse-radar（观测→治理→飞轮），用坏样本/质量分数驱动意图模型迭代（见 BACKLOG F30）

> 完整训练记录、踩坑、优化手段：`docs/intent-model-training/` 见独立训练仓库（nexusai-intent-model）。
