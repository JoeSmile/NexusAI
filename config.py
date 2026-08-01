"""应用配置 — pydantic-settings + Config 兼容代理（Task 19.03）"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = Path(__file__).parent / "config.env"
_PROFILE = (os.getenv("APP_ENV") or "dev").strip().lower() or "dev"
_PROFILE_PATH = Path(__file__).parent / "config" / f"{_PROFILE}.env"

# 优先级: shell 环境变量 > config.env(本地覆盖)> config/{APP_ENV}.env > 默认值
# override=False: 已存在的环境变量不被文件覆盖
load_dotenv(_ENV_PATH, override=False)
if _PROFILE_PATH.exists():
    load_dotenv(_PROFILE_PATH, override=False)

_env_files = [str(_ENV_PATH)]
if _PROFILE_PATH.exists():
    _env_files.append(str(_PROFILE_PATH))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=tuple(_env_files),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    project_root: str = Field(default_factory=lambda: str(Path(__file__).parent))

    # LLM（env fallback；运行时优先 KeyManager）
    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    openai_api_key: str = ""
    deepseek_base_url: str = ""
    api_base_url: str = ""

    # LangChain / LangSmith（SDK 也可直接读 env）
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_endpoint: str = ""

    database_url: str = (
        "postgresql://contextgate:contextgate_local@localhost:5432/contextgate"
    )

    default_model: str = ""
    deepseek_model: str = "glm-5.1"
    temperature: float = 0.7
    max_tokens: int = 1000

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    llm_key_master_key: str = ""

    redis_url: str = "redis://localhost:6379"
    cache_ttl: int = 3600

    cors_allow_all: bool = False
    frontend_origins: str = ""

    hermes_tools_enabled: bool = False
    hermes_workspace_root: str = ""
    hermes_web_fetch_enabled: bool = False
    hermes_web_allowlist: str = ""
    hermes_web_max_bytes: int = 524288
    hermes_shell_enabled: bool = False
    hermes_shell_timeout_sec: int = 60

    # RAG deepening (Task 20.01)
    rag_hyde_enabled: bool = False
    rag_rerank_enabled: bool = False
    rag_rerank_pool_size: int = 20

    @model_validator(mode="after")
    def _resolve_fallbacks(self) -> Settings:
        if not self.llm_api_key:
            self.llm_api_key = (
                self.deepseek_api_key
                or self.dashscope_api_key
                or self.openai_api_key
                or ""
            )
        if not self.llm_base_url or self.llm_base_url == "https://open.bigmodel.cn/api/paas/v4/":
            alt = self.deepseek_base_url or self.api_base_url
            if alt:
                self.llm_base_url = alt
        if not self.default_model:
            self.default_model = self.deepseek_model or "glm-5.1"
        return self


@lru_cache
def get_settings() -> Settings:
    """惰性创建 + 缓存 — 首次调用时读取 env。"""
    return Settings()


class ConfigProxy:
    """旧 `Config.LLM_API_KEY` 接口兼容层。"""

    _COMPAT = {
        "OPENAI_API_KEY": "llm_api_key",
        "API_BASE_URL": "llm_base_url",
        "DASHSCOPE_API_KEY": "llm_api_key",
        "LLM_API_KEY_FALLBACK": "llm_api_key",
        "LLM_BASE_URL_FALLBACK": "llm_base_url",
        "CHROMA_PERSIST_DIRECTORY": None,
    }

    def __getattr__(self, name: str):
        s = get_settings()
        mapped = self._COMPAT.get(name)
        if name in self._COMPAT:
            if mapped is None:
                return None
            return getattr(s, mapped)

        key = name.lower()
        if hasattr(s, key):
            return getattr(s, key)

        for field in type(s).model_fields:
            if field.upper() == name:
                return getattr(s, field)

        raise AttributeError(f"Config has no attribute {name}")


Config = ConfigProxy()
