"""종목 선정 퍼널의 기계적 필터 단계 (docs/rebalancer-design.md §4의 ①②③).

④(개별 DCF/RIM), ⑤(정성 필터), ⑥(분산 제약)는 사람이 개입하거나 별도 모듈
(weighting.py)이 다루므로 여기서는 다루지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StockProfile:
    """유니버스 스크리닝에 필요한 최소 정보."""

    ticker: str
    is_managed_issue: bool  # 관리종목
    is_trading_halted: bool
    is_spac: bool
    is_preferred_share: bool
    audit_opinion: str  # "적정" / "한정" / "부적정" / "의견거절"
    market_cap: float
    avg_daily_trading_value: float
    debt_ratio: float  # 총부채/총자본
    interest_coverage_ratio: float
    consecutive_profit_years: int
    valuation_percentile: float  # 자기 역사적 PER/PBR 밴드 내 현재 위치 (0=최저, 1=최고)


@dataclass(frozen=True)
class ScreeningCriteria:
    market_cap_min: float = 100_000_000_000  # 1,000억원
    avg_daily_trading_value_min: float = 500_000_000  # 5억원
    debt_ratio_max: float = 2.0
    interest_coverage_min: float = 1.5
    consecutive_profit_years_min: int = 3
    valuation_percentile_max: float = 0.3


def passes_disqualification_filter(stock: StockProfile) -> bool:
    """① 결격 배제: 관리종목/거래정지/스팩/우선주/감사의견 비적정."""
    return not (
        stock.is_managed_issue
        or stock.is_trading_halted
        or stock.is_spac
        or stock.is_preferred_share
        or stock.audit_opinion != "적정"
    )


def passes_quality_filter(stock: StockProfile, criteria: ScreeningCriteria) -> bool:
    """② 재무 건전성/퀄리티: 규모·유동성·부채·이자보상·수익 지속성."""
    return (
        stock.market_cap >= criteria.market_cap_min
        and stock.avg_daily_trading_value >= criteria.avg_daily_trading_value_min
        and stock.debt_ratio <= criteria.debt_ratio_max
        and stock.interest_coverage_ratio >= criteria.interest_coverage_min
        and stock.consecutive_profit_years >= criteria.consecutive_profit_years_min
    )


def passes_valuation_prefilter(
    stock: StockProfile, criteria: ScreeningCriteria
) -> bool:
    """③ 저평가 후보 1차 필터: 자기 역사적 밴드 하위권만 통과시켜 ④(정밀 분석)
    비용을 아낀다."""
    return stock.valuation_percentile <= criteria.valuation_percentile_max


def screen_universe(
    stocks: list[StockProfile], criteria: ScreeningCriteria | None = None
) -> list[StockProfile]:
    """①→②→③ 순서로 필터를 적용해 정밀 분석(④) 후보 목록을 만든다."""
    criteria = criteria or ScreeningCriteria()
    survivors = [s for s in stocks if passes_disqualification_filter(s)]
    survivors = [s for s in survivors if passes_quality_filter(s, criteria)]
    survivors = [s for s in survivors if passes_valuation_prefilter(s, criteria)]
    return survivors
