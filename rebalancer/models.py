"""공용 데이터 구조.

밸류에이션·스크리닝·비중배분 모듈이 공유하는 값 객체를 모아둔다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ValuationMethod(StrEnum):
    DCF = "dcf"
    RIM = "rim"


@dataclass(frozen=True)
class FinancialSnapshot:
    """단일 회계연도 재무 스냅샷 (DART 등에서 수집한 값 기준)."""

    fiscal_year: int
    revenue: float
    operating_margin: float
    tax_rate: float
    total_equity: float
    net_debt: float
    shares_outstanding: float


@dataclass(frozen=True)
class DCFAssumptions:
    """2단계 FCFF DCF 가정. 시나리오(bear/base/bull)마다 하나씩 만든다."""

    forecast_years: int
    revenue_growth_rates: tuple[float, ...]
    operating_margin: float
    tax_rate: float
    capex_to_revenue: float
    da_to_revenue: float
    wc_change_to_revenue: float
    wacc: float
    terminal_growth: float

    def __post_init__(self) -> None:
        if len(self.revenue_growth_rates) != self.forecast_years:
            raise ValueError("revenue_growth_rates 길이는 forecast_years와 같아야 함")
        if self.wacc <= self.terminal_growth:
            raise ValueError("wacc는 terminal_growth보다 커야 함 (영구가치 발산 방지)")


@dataclass(frozen=True)
class RIMAssumptions:
    """잔여이익모델(RIM) 가정."""

    forecast_years: int
    roe_path: tuple[float, ...]
    cost_of_equity: float
    terminal_growth: float
    payout_ratio: float = 0.0

    def __post_init__(self) -> None:
        if len(self.roe_path) != self.forecast_years:
            raise ValueError("roe_path 길이는 forecast_years와 같아야 함")
        if self.cost_of_equity <= self.terminal_growth:
            raise ValueError("cost_of_equity는 terminal_growth보다 커야 함")


@dataclass(frozen=True)
class ScenarioValue:
    """bear/base/bull 3개 시나리오 값 묶음."""

    bear: float
    base: float
    bull: float


@dataclass(frozen=True)
class ValuationResult:
    method: ValuationMethod
    intrinsic_value_per_share: ScenarioValue
    current_price: float

    def safety_margin(self, scenario: str = "base") -> float:
        """(내재가치 - 현재가) / 내재가치. 양수면 저평가."""
        intrinsic_value = getattr(self.intrinsic_value_per_share, scenario)
        if intrinsic_value <= 0:
            return -1.0
        return (intrinsic_value - self.current_price) / intrinsic_value
