# ContextGate Examples — 前端测试用例

按功能拆分的自包含测试页(零依赖,单 HTML 文件,经 `/playground` 挂载)。
每个页面说明:测什么、前置条件(env / API key)、如何操作、预期结果。

## 快速开始

### 1. 环境配置

```bash
cp config.env.example config.env    # config.env 已 gitignore
# 编辑 config.env:
#   LLM_API_KEY=sk-xxx              # 你的 LLM key(deepseek/智谱/OpenAI 兼容)
#   LLM_BASE_URL=https://api.deepseek.com
#   DEFAULT_MODEL=deepseek-chat
```

| env 键 | 作用 | 默认 |
|--------|------|------|
| `APP_ENV` | 环境分层:dev / test / demo,加载 `config/{APP_ENV}.env` | dev |
| `LLM_PROVIDER` | mock(确定性伪响应)/ record(真实调用+落盘)/ replay(回放 fixture,未命中降级 mock)/ openai(始终真实) | replay |
| `LLM_API_KEY` | 主 LLM key(运行时优先 KeyManager 加密库) | 空 |
| `LLM_BASE_URL` / `DEFAULT_MODEL` | 模型端点与默认模型 | deepseek |
| `MODEL_CHEAP/GOOD/BEST` | model_router 三档模型 | deepseek-chat |
| `LANGFUSE_ENABLED` | LangFuse trace 开关(UI: http://localhost:3001) | true |
| `LLM_KEY_MASTER_KEY` | Task 18 加密主密钥(`secrets.token_hex(32)` 生成;不设则走 env 明文) | 空 |

### 环境分层与 Mock 策略

优先级:**shell 环境变量 > config.env(本地覆盖)> config/{APP_ENV}.env > 默认值**。

```bash
make run    # APP_ENV=dev  → LLM_PROVIDER=replay(离线回放,未命中降级 mock)
make test   # APP_ENV=test → LLM_PROVIDER=replay(CI 零成本确定性)
make demo   # APP_ENV=demo → LLM_PROVIDER=openai(演示用真实模型,先填 key)
```

**采集真实响应作为 fixture(一次,之后永久免费):**

```bash
LLM_PROVIDER=record make run   # 真实调用 LLM,响应落盘 data/mock_data/llm/
make run                       # 回 replay,同样的请求直接回放,零调用零波动
```

fixture 按 (model + messages) 哈希命名,随仓库提交,团队共享。

### 2. 获取 API Key(认证 X-API-Key)

三种方式:

```bash
# A. 种子脚本(最简单,输出新 key,只显示一次)
make seed        # 或 uv run python scripts/seed_api_keys.py

# B. 管理端点(admin 权限,需先用种子 key 登录)
curl -X POST http://localhost:8000/api/admin/api-keys \
  -H "X-API-Key: <种子key>" -H "Content-Type: application/json" \
  -d '{"tenant_id":"acme","user_id":"alice","role":"user","description":"test"}'

# C. 直接查库(仅本地开发)
#   key 只存 SHA256 哈希,原 key 不可恢复,只能重新生成
```

> 租户 `acme` / 用户 `alice` 的种子 key 由 `make seed` 创建。
> 401 `AUTH_001 missing_api_key` = header 没带对;403 = 权限不足(需 `chat:write` 等)。

### 3. 启动

```bash
make up          # docker compose 基础设施(postgres+pgvector+langfuse)
make db-init     # alembic 建表
make seed        # API key + 示例数据
make run         # uvicorn :8000
```

## 用例索引

| 文件 | 功能 | 测什么 |
|------|------|--------|
| `playground.html` | 综合(基础) | Chat 管线 / Admin key 管理 / Audit 日志 / System 状态 |
| `streaming.html` | SSE 流式 | `/chat/streaming` 流式 token、abort(内容过滤)、retraction(超长) |
| `intent.html` | 意图识别 | `/intent/analyze` + `/detect`:对接意图模型,配置 env/key 后返回意图+置信度 |
| `rag.html` | RAG 知识库 | `/api/rag/ask` / `search` / `upload/pdf` / `init/sample` 全链路 |
| `agent.html` | Agent 模块 | `/agent/chat` 多轮、`/memory`、`/tools`、`/followup` 回访 |
| `admin.html` | 管理 API | api-keys 增删 / llm-keys 加密管理 / pending-requests 审批 / audit 导出 |
| `eval.html` | 评测 | `/evaluation/evaluate` / `batch` / `compare-prompts` 响应对比 |

## 对接外部模型(以意图识别为例)

意图识别(`intent.html`)默认走内置规则+LLM 兜底。要对接专用意图模型(如智谱 GLM / 本地 vLLM):

1. **配置 env**(config.env):
   ```bash
   LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/   # 智谱 OpenAI 兼容端点
   LLM_API_KEY=your-zhipu-key
   DEFAULT_MODEL=glm-5.1
   ```
   > 或注册到 ModelRegistry(Task 21.01 后):`backend/core/model_registry.py` 加一条 `{name, base_url, api_key_ref}`。

2. **通过 KeyManager 加密入库**(推荐,key 不落 env):
   ```bash
   # 先设 LLM_KEY_MASTER_KEY(64 hex),再调管理端点
   curl -X POST http://localhost:8000/api/admin/llm-keys \
     -H "X-API-Key: <管理key>" -H "Content-Type: application/json" \
     -d '{"provider":"zhipu","api_key":"sk-xxx","model":"glm-5.1"}'
   ```

3. **验证**:打开 `/playground/intent.html`,输入企业问题(如"如何查询公司的信息安全管理制度?"),确认返回:
   ```json
   {"intent": "knowledge_query", "confidence": 0.92, ...}
   ```
   开发默认 `LLM_PROVIDER=replay`(fixture 回放,未命中降级 mock);要采真实意图数据:`LLM_PROVIDER=record make run` 跑一次,之后 replay 永久回放。

## 常见问题

- **401**:X-API-Key 缺失/错误 → `make seed` 拿新 key
- **404**:服务没起或端点路径错 → 对照用例索引的路径
- **streaming 无输出**:`LLM_MOCK=false` 且 key 无效时 harness 降级 mock,属预期;检查 key
- **页面样式**:所有页面自带内联 CSS,无外部依赖,断网可用

> 每个页面 URL 前缀:`http://localhost:8000/playground/<file>.html`
