"""S2 — tiktoken cl100k_base prompt token estimates (not billing/quota)."""

from __future__ import annotations

import packages.prompt_tokens as pt


def setup_function() -> None:
    pt.reset_for_tests()


def test_chinese_counts_more_than_len_div_4() -> None:
    text = "用户背景仅供参考不改变你的角色" * 20
    est = pt.estimate_tokens(text)
    assert est > max(1, len(text) // 4)
    assert est >= len(text)  # CJK is not 4-chars-per-token


def test_mixed_chinese_english() -> None:
    text = "你好 world，请总结这份合同条款 NexusAI"
    est = pt.estimate_tokens(text)
    assert est >= 8
    assert est < len(text) * 2


def test_empty_is_at_least_one() -> None:
    assert pt.estimate_tokens("") == 1
    assert pt.estimate_tokens(None) == 1  # type: ignore[arg-type]


def test_fallback_han_times_one_other_div_4(monkeypatch) -> None:
    monkeypatch.setattr(pt, "_load_encoder", lambda: None)
    pt.reset_for_tests()
    text = "你好hello"
    # 2 han + 5 other → 2 + 5//4 = 3
    assert pt.fallback_estimate_tokens(text) == 3
    assert pt.estimate_tokens(text) == 3


def test_trim_token_budget_is_85_percent() -> None:
    assert pt.trim_token_budget(100) == 85
    assert pt.trim_token_budget(8000) == 6800
    assert pt.trim_token_budget(1) == 1


def test_token_budget_warning_uses_true_tokens() -> None:
    from packages.plan.retrieval_mode import token_budget_warning

    blob = "你" * 9000
    assert len(blob) // 4 < 8000
    warn = token_budget_warning(blob, budget=8000)
    assert warn is not None
    assert warn.startswith("context_budget_exceeded:")
