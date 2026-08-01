"""LangFuse 路径采样（Task 23.02）"""

from __future__ import annotations

from types import SimpleNamespace

import backend.observability.sampling as sampling


def _settings(short: float, long: float = 1.0):
    return SimpleNamespace(
        langfuse_sample_short_path=short,
        langfuse_sample_long_path=long,
    )


def test_is_short_path_set():
    assert sampling.is_short_path("skill_executed")
    assert sampling.is_short_path("cache_hit")
    assert sampling.is_short_path("blocked")
    assert not sampling.is_short_path("llm_generated")
    assert not sampling.is_short_path(None)


def test_should_sample_short_rate_zero(monkeypatch):
    monkeypatch.setattr(
        "config.get_settings", lambda: _settings(short=0.0, long=1.0)
    )
    sampling.reset_sampling_state()
    assert sampling.should_sample("skill_executed") is False


def test_should_sample_short_rate_one(monkeypatch):
    monkeypatch.setattr(
        "config.get_settings", lambda: _settings(short=1.0, long=1.0)
    )
    sampling.reset_sampling_state()
    assert sampling.should_sample("cache_hit") is True


def test_should_sample_long_path_full(monkeypatch):
    monkeypatch.setattr(
        "config.get_settings", lambda: _settings(short=0.0, long=1.0)
    )
    sampling.reset_sampling_state()
    assert sampling.should_sample("llm_generated") is True


def test_should_sample_idempotent(monkeypatch):
    monkeypatch.setattr(
        "config.get_settings", lambda: _settings(short=0.5, long=0.5)
    )
    monkeypatch.setattr(sampling.random, "random", lambda: 0.9)
    sampling.reset_sampling_state()
    first = sampling.should_sample("skill_executed")
    # 即使 random 翻转，同请求结果不变
    monkeypatch.setattr(sampling.random, "random", lambda: 0.0)
    second = sampling.should_sample("skill_executed")
    assert first is False
    assert second is False


def test_reset_allows_new_roll(monkeypatch):
    monkeypatch.setattr(
        "config.get_settings", lambda: _settings(short=0.5, long=0.5)
    )
    monkeypatch.setattr(sampling.random, "random", lambda: 0.9)
    sampling.reset_sampling_state()
    assert sampling.should_sample("skill_executed") is False
    monkeypatch.setattr(sampling.random, "random", lambda: 0.0)
    sampling.reset_sampling_state()
    assert sampling.should_sample("skill_executed") is True
