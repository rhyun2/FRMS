"""안전마진 → 목표비중 변환 (docs/rebalancer-design.md §5).

안전마진을 그대로 선형 비중으로 쓰면 밸류에이션 추정 오차가 그대로 비중에
반영되고, 안전마진이 가장 큰 종목 하나에 몰빵하는 결과가 나오기 쉽다. 그래서
클리핑 → 체감(비선형) 변환 → 리스크 조정 → 베이스라인 블렌딩 → 정규화/캡
순서로 감쇠시킨다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class WeightingConfig:
    margin_clip_lower: float = -0.30
    margin_clip_upper: float = 0.50
    exit_margin_threshold: float = -0.30  # 이 이하면 강제 편출(비중 0)
    alpha: float = 0.4  # 밸류에이션 모델 신뢰도 (0=베이스라인만, 1=밸류 스코어만)
    min_weight: float = 0.03
    max_weight: float = 0.25


def clip_margin(margin: float, config: WeightingConfig) -> float:
    return max(config.margin_clip_lower, min(config.margin_clip_upper, margin))


def nonlinear_transform(clipped_margin: float) -> float:
    """부호를 보존하는 제곱근 변환으로 안전마진이 커질수록 증분 기여를 체감시킨다."""
    return math.copysign(math.sqrt(abs(clipped_margin)), clipped_margin)


def risk_adjust(score: float, volatility: float) -> float:
    if volatility <= 0:
        raise ValueError("volatility는 0보다 커야 함")
    return score / volatility


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return dict.fromkeys(weights, 0.0)
    return {k: v / total for k, v in weights.items()}


def blend_with_baseline(
    risk_adjusted_scores: dict[str, float],
    baseline_weights: dict[str, float],
    alpha: float,
) -> dict[str, float]:
    """밸류에이션 점수(양수만 반영)를 베이스라인 비중과 블렌딩한다.

    음(-)의 리스크조정 점수는 '비중을 늘릴 근거 없음'을 뜻할 뿐이므로 블렌딩
    입력에서는 0으로 취급한다 (롱온리 가정). 강제 편출은 apply_caps 이전
    단계에서 별도 처리한다.
    """
    positive_scores = {k: max(v, 0.0) for k, v in risk_adjusted_scores.items()}
    value_weights = _normalize(positive_scores)
    return {
        ticker: alpha * value_weights.get(ticker, 0.0)
        + (1 - alpha) * baseline_weights.get(ticker, 0.0)
        for ticker in risk_adjusted_scores
    }


def apply_caps(
    weights: dict[str, float],
    min_weight: float,
    max_weight: float,
    max_iterations: int = 50,
) -> dict[str, float]:
    """상한 초과분을 나머지 종목에 비례 재분배(waterfall)하고, 하한 미만은
    0으로 잘라낸 뒤 재정규화한다.

    편출(margin<=threshold)로 이미 0이 된 종목은 재분배 대상에서 영원히
    제외되므로, 남은 종목 수만으로 max_weight 상한을 지키며 합계 100%를
    채울 수 있어야 한다. 그렇지 않으면(예: 후보가 3종목인데 max_weight=25%)
    조용히 상한을 어기거나 무한 재귀에 빠지는 대신 즉시 에러를 낸다.
    """
    weights = dict(weights)

    eligible_count = sum(1 for v in weights.values() if v > 0)
    if eligible_count > 0 and eligible_count * max_weight < 1.0 - 1e-9:
        raise ValueError(
            "max_weight 상한으로는 생존 종목 수만으로 합계 100%를 채울 수 "
            "없습니다. 종목 수를 늘리거나 max_weight를 높이세요 "
            f"(생존 종목 {eligible_count}개 x max_weight {max_weight} < 1.0)."
        )

    for _ in range(max_iterations):
        over_cap = {k: v for k, v in weights.items() if v > max_weight}
        if not over_cap:
            break
        excess = sum(v - max_weight for v in over_cap.values())
        for ticker in over_cap:
            weights[ticker] = max_weight
        recipients = {k: v for k, v in weights.items() if k not in over_cap}
        recipients_total = sum(recipients.values())
        if recipients_total <= 0:
            break
        for ticker in recipients:
            weights[ticker] += excess * (weights[ticker] / recipients_total)

    weights = {k: (v if v >= min_weight else 0.0) for k, v in weights.items()}
    weights = _normalize(weights)

    # 하한 컷으로 재분배된 몫이 다시 상한을 넘을 수 있으므로 한 번 더 캡을 건다.
    if any(v > max_weight for v in weights.values()):
        return apply_caps(weights, min_weight, max_weight, max_iterations)
    return weights


def compute_target_weights(
    safety_margins: dict[str, float],
    volatilities: dict[str, float],
    baseline_weights: dict[str, float] | None = None,
    config: WeightingConfig | None = None,
) -> dict[str, float]:
    """전체 파이프라인: 안전마진 → 목표비중.

    Args:
        safety_margins: 종목별 안전마진 (ValuationResult.safety_margin() 결과).
        volatilities: 종목별 연변동성 (>0).
        baseline_weights: 균등비중 등 베이스라인. 미지정 시 종목 수로 균등분배.
        config: 임계값/파라미터. 미지정 시 기본값 사용.
    """
    config = config or WeightingConfig()
    tickers = list(safety_margins)
    if baseline_weights is None:
        baseline_weights = dict.fromkeys(tickers, 1 / len(tickers)) if tickers else {}

    risk_adjusted_scores = {}
    for ticker in tickers:
        clipped = clip_margin(safety_margins[ticker], config)
        transformed = nonlinear_transform(clipped)
        risk_adjusted_scores[ticker] = risk_adjust(transformed, volatilities[ticker])

    blended = blend_with_baseline(risk_adjusted_scores, baseline_weights, config.alpha)

    # 심한 고평가 종목은 블렌딩 결과와 무관하게 강제 편출한다.
    for ticker in tickers:
        if safety_margins[ticker] <= config.exit_margin_threshold:
            blended[ticker] = 0.0
    blended = _normalize(blended)

    return apply_caps(blended, config.min_weight, config.max_weight)
