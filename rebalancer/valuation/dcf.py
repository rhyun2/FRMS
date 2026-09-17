"""2단계 FCFF DCF (Discounted Cash Flow).

제조업/IT 등 FCF가 사업 실질을 잘 반영하는 업종에 적용한다. 금융업/지주회사는
rim.py를 대신 쓴다 (docs/rebalancer-design.md §3 참조).

WACC·영구성장률 가정에 결과가 극도로 민감하므로 항상 시나리오(bear/base/bull)
3개로 계산하고 단일 값을 신뢰하지 않는다.
"""

from __future__ import annotations

from rebalancer.models import DCFAssumptions, FinancialSnapshot, ScenarioValue


def _forecast_fcff(base_revenue: float, assumptions: DCFAssumptions) -> list[float]:
    """예측기간 연도별 FCFF = NOPAT + D&A - Capex - ΔWC."""
    fcff_by_year: list[float] = []
    revenue = base_revenue
    for growth_rate in assumptions.revenue_growth_rates:
        revenue *= 1 + growth_rate
        ebit = revenue * assumptions.operating_margin
        nopat = ebit * (1 - assumptions.tax_rate)
        depreciation_amortization = revenue * assumptions.da_to_revenue
        capex = revenue * assumptions.capex_to_revenue
        working_capital_change = revenue * assumptions.wc_change_to_revenue
        fcff = nopat + depreciation_amortization - capex - working_capital_change
        fcff_by_year.append(fcff)
    return fcff_by_year


def intrinsic_value_per_share(
    financials: FinancialSnapshot, assumptions: DCFAssumptions
) -> float:
    """단일 시나리오 가정으로 주당 내재가치를 계산한다."""
    fcff_by_year = _forecast_fcff(financials.revenue, assumptions)

    present_value_sum = 0.0
    for year_index, fcff in enumerate(fcff_by_year, start=1):
        present_value_sum += fcff / (1 + assumptions.wacc) ** year_index

    terminal_fcff = fcff_by_year[-1]
    terminal_value = (
        terminal_fcff
        * (1 + assumptions.terminal_growth)
        / (assumptions.wacc - assumptions.terminal_growth)
    )
    present_value_of_terminal_value = terminal_value / (
        1 + assumptions.wacc
    ) ** assumptions.forecast_years

    enterprise_value = present_value_sum + present_value_of_terminal_value
    equity_value = enterprise_value - financials.net_debt

    return equity_value / financials.shares_outstanding


def run_scenarios(
    financials: FinancialSnapshot,
    bear: DCFAssumptions,
    base: DCFAssumptions,
    bull: DCFAssumptions,
) -> ScenarioValue:
    """bear/base/bull 3개 가정으로 각각 계산해 시나리오 레인지를 만든다."""
    return ScenarioValue(
        bear=intrinsic_value_per_share(financials, bear),
        base=intrinsic_value_per_share(financials, base),
        bull=intrinsic_value_per_share(financials, bull),
    )
