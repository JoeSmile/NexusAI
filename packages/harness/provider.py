"""LLM Provider 路由 — mock / record / replay / openai

框架级 mock 策略:
- `mock`   确定性伪响应(不调外部、零成本,适合快速跑通链路)
- `record` 真实调用 LLM,响应落盘为 fixture(data/mock_data/llm/)
- `replay` 回放 fixture;未命中时降级 mock(开发/测试/演示主力)
- `openai` 始终真实调用(默认,兼容旧 LLM_MOCK=false 行为)

优先级: shell env > config.env > config/{APP_ENV}.env > 默认值
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "mock_data" / "llm"

_PROVIDERS = ("mock", "record", "replay", "openai")


def get_llm_provider() -> str:
    """解析 LLM_PROVIDER;兼容旧 LLM_MOCK 布尔开关。"""
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p in _PROVIDERS:
        return p
    # 旧配置兼容:LLM_MOCK=true → mock;LLM_MOCK=false/未设 → openai
    return "mock" if os.getenv("LLM_MOCK", "true").lower() == "true" else "openai"


def _fixture_path(model: str, messages: list[dict]) -> Path:
    digest = hashlib.sha256(
        json.dumps({"model": model, "messages": messages}, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    safe_model = model.replace("/", "_").replace(":", "_")
    return FIXTURE_DIR / f"{safe_model}-{digest}.json"


def load_fixture(model: str, messages: list[dict]) -> str | None:
    """回放:命中返回响应文本,未命中返回 None。"""
    try:
        data = json.loads(_fixture_path(model, messages).read_text(encoding="utf-8"))
        return str(data["response"])
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None


def save_fixture(model: str, messages: list[dict], response: str) -> None:
    """录制:真实响应落盘,供 replay 使用。"""
    try:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": model,
            "messages": messages,
            "response": response,
            "provider": "recorded",
        }
        _fixture_path(model, messages).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass  # 录制失败不阻塞请求


def mock_response(model: str, prompt: str) -> str:
    """确定性伪响应:回显 prompt 片段,稳定可断言。"""
    snippet = prompt.strip().replace("\n", " ")[-180:]
    return f"[mock:{model or 'default'}] 已收到：{snippet}"
