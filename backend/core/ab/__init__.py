"""A/B 实验框架 — 分流、曝光、变体配置注入。"""

from backend.core.ab.service import assign_variant, get_active_experiment, record_event

__all__ = ["assign_variant", "get_active_experiment", "record_event"]
