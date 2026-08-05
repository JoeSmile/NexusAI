【一句话本质】
    harness = 所有 LLM 调用的唯一出口,把"调模型"从裸调用升级为:模式路由(mock/record/replay/openai)+ 断路器 + 重试 + 超时 + 预算预检 + 成本记账 + LangFuse 观测 + key failover 的一体化 wrapper。规则:禁绕过
    harness 直读 LLM_API_KEY(EVID-08),RAG/Agent/Eval 旁路也必须走 get_llm_client()。

    【四模式(provider.py:1-30,路由在 get_llm_provider)】
    - mock:确定性伪响应(回显 prompt 后 180 字符,provider.py:67-70),零成本零外部依赖,单测可断言
    - record:真实调 LLM,响应落盘为 fixture(data/mock_data/llm/{model}-{sha256}.json)——录制
    - replay:回放 fixture,未命中降级 mock(provider.py:41-47)——开发/演示/测试主力
    - openai:始终真实调用(默认档)
    - 兼容旧开关:LLM_MOCK=true/false → mock/openai(provider.py:24-30);优先级 env > config.env > config/{APP_ENV}.env

    【三层架构】
    1. base.py:Harness 通用 wrapper(不止 LLM 能用)
       - 断路器:5 次失败 → 熔断 30s(base.py:33-35)
       - 重试:3 次,指数退避 2^n 秒(base.py:83-93)
       - 超时:asyncio.wait_for,默认 30s,可配(base.py:54-57)
       - 计时 + metrics:errors_total / request_duration(base.py:95-105)
       - 错误分类:timeout 单独处理,可带 fallback 返回值
    2. llm.py:LLMHarness
       - generate():预算预检 → 模式路由 → wrap → 成功后 token 统计 + 成本记账 + LangFuse 回填(llm.py:33-115)
       - stream():真流式(OpenAI-compatible astream),失败自动降级非流式,断开传播 CancelledError(llm.py:117-210)
       - _call_api():真实调用 + 候选链切 key(llm.py:211-273)
    3. provider.py:模式路由 + fixture 读写 + mock 生成

    【六大横切能力(都在 wrap 里,llm.py:75-87)】
    断路器 / 指数重试 / 超时 / 计时 / metrics / fallback——任何一个 LLM 调用自动获得,不用每个调用点自己写。

    【关键集成点】
    - 预算:estimate_cost → check_budget,超限直接 COST_001 拒绝(llm.py:42-50)——花钱前先问钱包
    - 成本:count_tokens → calculate_cost → record_consumption(llm.py:92-94),Task 32 预算引擎的数据源
    - LangFuse:update_current_observation(model/input/output/usage)(llm.py:96-106)
    - Key failover(Task 27):get_key_chain(limit=3)取候选链 → call_with_key_failover
      - 只对 401/429 切 key;5xx/超时不切(留给断路器)——错误分类职责分离(key_failover.py:13-15)
      - 切 key 事件写审计(key_failover.py:_audit_failover)

    【fixture 机制】
    - key = sha256(json{model, messages}):16——相同请求精确复现
    - record 落盘、replay 读取、未命中降级 mock;save_fixture 失败静默不阻塞(provider.py:50-64)

    【统一客户端工厂 llm_client.py(get_llm_client)】
    - RAG/Agent/Eval 旁路统一入口:mock/replay 不依赖 key,openai/record 走 failover(llm_client.py:343-380)
    - 双形态:LangChain BaseChatModel 适配(接 LC 链)+ _FallbackLLMClient(无 LangChain 兜底)
    - 同步 complete_via_provider + 异步 acomplete_chat(异步先预载候选链,避免线程池同步加载,llm_client.py:240-258)

    【面试怎么讲(决策故事)】
    1. "为什么禁绕过 harness?"——单一出口才能让 mock/record/replay 全局生效;否则谁直读 LLM_API_KEY,谁就在测试/演示环境里偷偷花钱、不可回放
    2. "为什么 401/429 切 key、5xx 不切?"——错误分类职责:限流/鉴权是"这把钥匙不行",换钥匙;服务端故障是"门坏了",该熔断不是换钥匙
    3. "为什么 mock 是确定性回显?"——单测要可断言;回显 prompt 片段让每个测试都能验证"请求确实发到了 LLM 层"
    4. "replay 是开发主力?"——离线可跑、成本为零、行为与真实一致;录制一次真实响应,全团队共享 fixture
