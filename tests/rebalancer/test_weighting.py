from __future__ import annotations

import math

import pytest

from rebalancer.weighting import (
    WeightingConfig,
    apply_caps,
    blend_with_baseline,
    clip_margin,
    compute_target_weights,
    nonlinear_transform,
    risk_adjust,
)


def test_clip_margin_clamps_to_configured_bounds():
    config = WeightingConfig(margin_clip_lower=-0.30, margin_clip_upper=0.50)

    assert clip_margin(0.80, config) == 0.50
    assert clip_margin(-0.90, config) == -0.30
    assert clip_margin(0.10, config) == 0.10


def test_nonlinear_transform_preserves_sign_and_dampens_large_values():
    assert nonlinear_transform(0.25) == pytest.approx(0.5)
    assert nonlinear_transform(-0.25) == pytest.approx(-0.5)
    assert nonlinear_transform(0.0) == 0.0

    # 체감: margin이 4배가 되어도 transform은 2배만 증가 (sqrt)
    assert nonlinear_transform(0.16) == pytest.approx(2 * nonlinear_transform(0.04))


def test_risk_adjust_divides_by_volatility():
    assert risk_adjust(0.5, 0.25) == pytest.approx(2.0)


def test_risk_adjust_rejects_non_positive_volatility():
    with pytest.raises(ValueError):
        risk_adjust(0.5, 0.0)


def test_blend_with_baseline_alpha_zero_returns_pure_baseline():
    scores = {"A": 5.0, "B": -1.0}
    baseline = {"A": 0.6, "B": 0.4}

    blended = blend_with_baseline(scores, baseline, alpha=0.0)

    assert blended == pytest.approx(baseline)


def test_blend_with_baseline_ignores_negative_scores_in_value_component():
    scores = {"A": 1.0, "B": -1.0}
    baseline = {"A": 0.5, "B": 0.5}

    blended = blend_with_baseline(scores, baseline, alpha=1.0)

    assert blended["A"] == pytest.approx(1.0)
    assert blended["B"] == pytest.approx(0.0)


def test_apply_caps_redistributes_excess_and_sums_to_one():
    # 5개 종목, cap=0.30 → 초과분을 나머지에 나눠줘도 여유가 있어 실현 가능한 사례.
    # (참고: N개 종목에 cap=c일 때 N*c < 1 이면 상한을 지키며 합계 1을 만들 수
    # 없으므로 테스트에서는 항상 N*c >= 1 인 조합만 써야 한다.)
    weights = {"A": 0.50, "B": 0.15, "C": 0.15, "D": 0.10, "E": 0.10}

    capped = apply_caps(weights, min_weight=0.03, max_weight=0.30)

    assert capped["A"] == pytest.approx(0.30)
    assert sum(capped.values()) == pytest.approx(1.0)
    assert all(v <= 0.30 + 1e-9 for v in capped.values())


def test_apply_caps_zeroes_out_below_min_weight_and_renormalizes():
    weights = {"A": 0.90, "B": 0.05, "C": 0.05}

    capped = apply_caps(weights, min_weight=0.06, max_weight=1.0)

    assert capped["B"] == 0.0
    assert capped["C"] == 0.0
    assert capped["A"] == pytest.approx(1.0)


def test_compute_target_weights_sums_to_one():
    margins = {"A": 0.30, "B": 0.10, "C": -0.05, "D": 0.20}
    volatilities = {"A": 0.25, "B": 0.20, "C": 0.30, "D": 0.22}

    weights = compute_target_weights(margins, volatilities)

    assert sum(weights.values()) == pytest.approx(1.0)


def test_compute_target_weights_excludes_deeply_overvalued_stock():
    margins = {"A": 0.30, "B": -0.40}  # B는 exit_margin_threshold(-0.30) 이하
    volatilities = {"A": 0.25, "B": 0.25}
    # 생존 종목이 1개뿐이라 기본 max_weight(0.25)로는 100%를 채울 수 없으므로
    # (아래 별도 테스트 참조) 상한을 완화해 편출 로직 자체만 검증한다.
    config = WeightingConfig(max_weight=1.0, min_weight=0.0)

    weights = compute_target_weights(margins, volatilities, config=config)

    assert weights["B"] == 0.0
    assert weights["A"] == pytest.approx(1.0)


def test_apply_caps_raises_when_survivors_cannot_fill_100_percent_under_cap():
    # 3종목 x max_weight 0.25 = 0.75 < 1.0 → 상한을 지키며 합계 100%를
    # 채우는 것 자체가 수학적으로 불가능한 구성.
    weights = {"A": 0.5, "B": 0.3, "C": 0.2}

    with pytest.raises(ValueError):
        apply_caps(weights, min_weight=0.0, max_weight=0.25)


def test_compute_target_weights_respects_max_weight_cap():
    margins = {"A": 0.50, "B": 0.01, "C": 0.01, "D": 0.01}
    volatilities = {"A": 0.15, "B": 0.30, "C": 0.30, "D": 0.30}
    config = WeightingConfig(max_weight=0.30, min_weight=0.0)

    weights = compute_target_weights(margins, volatilities, config=config)

    assert weights["A"] <= 0.30 + 1e-9
    assert sum(weights.values()) == pytest.approx(1.0)


def test_compute_target_weights_higher_margin_gets_higher_weight_at_full_alpha():
    margins = {"A": 0.40, "B": 0.10}
    volatilities = {"A": 0.20, "B": 0.20}
    config = WeightingConfig(alpha=1.0, min_weight=0.0, max_weight=1.0)

    weights = compute_target_weights(margins, volatilities, config=config)

    assert weights["A"] > weights["B"]
