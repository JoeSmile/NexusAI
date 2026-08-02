# QA — 人工测试用例索引

> 按大类独立成册: 每个文件夹 = 用例清单(README.md)+ 可跑脚本(能自动化的部分)。
> 总纲(回归基线/缺陷表/Demo 剧本)仍在 `docs/MANUAL_TEST.md`。
> 原则: 不靠自述,一切以实机 curl / 页面操作结果为准;发现的缺口记入 MANUAL_TEST §13。

| 大类 | 页面 | 用例 | 一键脚本 |
|------|------|------|---------|
| chat — Chat 管线 | playground.html | [README](chat/README.md)(3.1-3.7) | `chat/chat_pipeline_qa.sh` |
| rag — RAG 知识库 | rag.html | MANUAL_TEST §6(6.1-6.17) | `scripts/rag_cache_qa.sh` |

> 其余大类(冒烟/认证/SSE/意图/Agent/Admin/评测/可观测/安全/Demo)陆续迁入。
> 新增大类约定: 建 `examples/qa/<大类>/`,README 写用例表(操作/预期/通过标准),curl 可自动化的配 `.sh`。
