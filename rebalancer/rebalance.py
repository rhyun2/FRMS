"""밴드 기반 리밸런싱 실행 트리거 (docs/rebalancer-design.md §6).

목표비중이 나와도 미세한 괴리마다 매매하면 거래비용·세금이 낭비되므로,
현재비중과 목표비중의 차이가 band 이상일 때만 매매를 발생시킨다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RebalanceAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class RebalanceOrder:
    ticker: str
    current_weight: float
    target_weight: float
    drift: float  # target - current
    action: RebalanceAction


def compute_rebalance_orders(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    band: float = 0.05,
) -> list[RebalanceOrder]:
    tickers = sorted(set(current_weights) | set(target_weights))
    orders = []
    for ticker in tickers:
        current = current_weights.get(ticker, 0.0)
        target = target_weights.get(ticker, 0.0)
        drift = target - current

        if abs(drift) < band:
            action = RebalanceAction.HOLD
        elif drift > 0:
            action = RebalanceAction.BUY
        else:
            action = RebalanceAction.SELL

        orders.append(RebalanceOrder(ticker, current, target, drift, action))
    return orders
