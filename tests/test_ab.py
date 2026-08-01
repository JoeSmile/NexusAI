"""A/B 分流纯函数测试（Task 22.02）"""

from __future__ import annotations

from backend.core.ab.service import _pick_variant, _stable_bucket


def test_pick_variant_deterministic():
    groups = ["A", "B"]
    weights = [0.5, 0.5]
    assert _pick_variant(0.1, groups, weights) == _pick_variant(0.1, groups, weights)
    assert _pick_variant(0.1, groups, weights) == "A"
    assert _pick_variant(0.6, groups, weights) == "B"


def test_pick_variant_boundaries():
    groups = ["A", "B", "C"]
    weights = [0.3, 0.3, 0.4]
    assert _pick_variant(0.0, groups, weights) == "A"
    # score 逼近 1 → 最后一组（cumulative 用 <）
    assert _pick_variant(0.999999, groups, weights) == "C"


def test_pick_variant_distribution_50_50():
    groups = ["A", "B"]
    weights = [0.5, 0.5]
    n = 1000
    counts = {"A": 0, "B": 0}
    for i in range(n):
        # 均匀覆盖 [0,1)
        score = (i + 0.5) / n
        counts[_pick_variant(score, groups, weights)] += 1
    ratio_a = counts["A"] / n
    assert abs(ratio_a - 0.5) < 0.1


def test_stable_bucket_deterministic():
    a = _stable_bucket("user-1", "exp-x")
    b = _stable_bucket("user-1", "exp-x")
    c = _stable_bucket("user-2", "exp-x")
    assert a == b
    assert 0.0 <= a < 1.0
    assert a != c
