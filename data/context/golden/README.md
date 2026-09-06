# S4 案 A 合成 golden（无真实对话）

未上线、无生产日志时用**合成场景**。独立于 `data/intent/golden/`。

- 文件: `s4_case_a.jsonl`（≥30 条）
- 单测: `tests/test_s4_case_a.py` 做**结构门禁**（背景在最终 user、不在 system）
- 实验室 LLM 门禁（背景≥90% / 漂移 0 / 营销越界 0）需真模型，设 `RUN_S4_GOLDEN_LAB=1` 才跑；缺文件或未设则 skip
