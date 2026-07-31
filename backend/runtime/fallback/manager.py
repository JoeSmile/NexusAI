"""
FallbackManager — 模型降级管理

当主模型不可用时，自动切换到备用模型。

LLM Gateway场景的降级策略：
- 主模型 → 备用模型 (如 GPT-4 → GPT-3.5)
- LLM 降级 → 规则式回应 (最极端的降级)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FallbackConfig:
    """降级配置"""

    primary_model: str = "gpt-4"
    fallback_models: list[str] = field(default_factory=lambda: ["gpt-3.5-turbo"])
    max_retries: int = 1
    timeout_seconds: float = 30.0
    # LLM Gateway扩展：最终降级使用规则式回应
    rule_based_fallback: bool = True


class FallbackManager:
    """
    降级管理器 — 自动管理模型切换

    Usage::

        manager = FallbackManager(config=FallbackConfig())
        llm = manager.get_llm()  # 返回当前活跃的 LLM
        manager.on_failure(reason="rate_limit")
    """

    def __init__(self, config: FallbackConfig | None = None, llm_client=None):
        self._config = config or FallbackConfig()
        self._llm = llm_client
        self._current_model = self._config.primary_model
        self._fallback_index = 0
        self._failure_count = 0
        self._is_fallback = False

    def get_llm(self) -> Any:
        """获取当前活跃的 LLM"""
        return self._llm

    def get_model_name(self) -> str:
        """获取当前模型名"""
        return self._current_model

    def on_failure(self, reason: str = "") -> bool:
        """
        处理失败 — 尝试降级

        Returns:
            True 如果成功降级，False 如果已无可用降级
        """
        self._failure_count += 1
        logger.warning("LLM failure (reason=%s), attempting fallback", reason)

        if self._fallback_index < len(self._config.fallback_models):
            self._current_model = self._config.fallback_models[self._fallback_index]
            self._fallback_index += 1
            self._is_fallback = True
            logger.info("Fell back to model: %s", self._current_model)
            return True

        if self._config.rule_based_fallback:
            self._current_model = "rule_based"
            self._is_fallback = True
            logger.info("Fell back to rule-based responses")
            return True

        return False

    def restore_primary(self) -> None:
        """恢复到主模型"""
        self._current_model = self._config.primary_model
        self._fallback_index = 0
        self._is_fallback = False
        self._failure_count = 0

    @property
    def is_fallback(self) -> bool:
        return self._is_fallback

    @property
    def current_model(self) -> str:
        return self._current_model
