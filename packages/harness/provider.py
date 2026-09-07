"""LLM Provider 路由 — mock / openai

- `mock`   确定性伪响应(不调外部、零成本,单测/本地开发用;tests/conftest 默认锁定)
- `openai` 始终真实调用(生产默认,config.env 显式配置)
- 旧 `LLM_MOCK` 布尔开关兼容:true → mock;false → openai
- record/replay(fixture 录制回放)已于 2026-09-07 移除,不再支持

优先级: shell env > config.env > config/{APP_ENV}.env > 默认值
"""

from __future__ import annotations

import os

_PROVIDERS = ("mock", "openai")


def get_llm_provider() -> str:
    """解析 LLM_PROVIDER;兼容旧 LLM_MOCK 布尔开关。"""
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p in _PROVIDERS:
        return p
    # 旧配置兼容:LLM_MOCK=true/未设 → mock;LLM_MOCK=false → openai
    return "mock" if os.getenv("LLM_MOCK", "true").lower() == "true" else "openai"


def mock_response(model: str, prompt: str) -> str:
    """确定性伪响应:回显 prompt 片段,稳定可断言。"""
    snippet = prompt.strip().replace("\n", " ")[-180:]
    return f"[mock:{model or 'default'}] 已收到：{snippet}"
