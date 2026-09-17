from __future__ import annotations

import pytest

from rebalancer.models import DCFAssumptions, FinancialSnapshot
from rebalancer.valuation import dcf


def _flat_assumptions(**overrides) -> DCFAssumptions:
    """capex == D&A, 성장률 0% → FCFF가 매년 NOPAT로 일정해서 손계산이 쉬운
    시나리오."""
    defaults = dict(
        forecast_years=5,
        revenue_growth_rates=(0.0, 0.0, 0.0, 0.0, 0.0),
        operating_margin=0.20,
        tax_rate=0.25,
        capex_to_revenue=0.05,
        da_to_revenue=0.05,
        wc_change_to_revenue=0.0,
        wacc=0.10,
        terminal_growth=0.02,
    )
    defaults.update(overrides)
    return DCFAssumptions(**defaults)


def _financials(**overrides) -> FinancialSnapshot:
    defaults = dict(
        fiscal_year=2025,
        revenue=1000.0,
        operating_margin=0.20,
        tax_rate=0.25,
        total_equity=2000.0,
        net_debt=0.0,
        shares_outstanding=100.0,
    )
    defaults.update(overrides)
    return FinancialSnapshot(**defaults)


def test_constant_fcff_matches_closed_form_annuity_plus_terminal_value():
    assumptions = _flat_assumptions()
    financials = _financials()

    fcff = 1000.0 * 0.20 * (1 - 0.25)  # NOPAT, capex/D&A는 상쇄, ΔWC=0
    wacc, n = assumptions.wacc, assumptions.forecast_years
    pv_annuity = fcff * (1 - (1 + wacc) ** -n) / wacc
    terminal_value = fcff * (1 + assumptions.terminal_growth) / (
        wacc - assumptions.terminal_growth
    )
    pv_terminal = terminal_value / (1 + wacc) ** n
    expected_value_per_share = (pv_annuity + pv_terminal - financials.net_debt) / (
        financials.shares_outstanding
    )

    actual = dcf.intrinsic_value_per_share(financials, assumptions)

    assert actual == pytest.approx(expected_value_per_share, rel=1e-9)


def test_higher_growth_yields_higher_intrinsic_value():
    financials = _financials()
    low_growth = _flat_assumptions(revenue_growth_rates=(0.0,) * 5)
    high_growth = _flat_assumptions(revenue_growth_rates=(0.05,) * 5)

    assert dcf.intrinsic_value_per_share(
        financials, high_growth
    ) > dcf.intrinsic_value_per_share(financials, low_growth)


def test_net_debt_reduces_equity_value_per_share():
    assumptions = _flat_assumptions()
    no_debt = _financials(net_debt=0.0)
    with_debt = _financials(net_debt=500.0)

    assert dcf.intrinsic_value_per_share(
        with_debt, assumptions
    ) < dcf.intrinsic_value_per_share(no_debt, assumptions)


def test_run_scenarios_orders_bear_base_bull():
    financials = _financials()
    bear = _flat_assumptions(revenue_growth_rates=(-0.02,) * 5)
    base = _flat_assumptions(revenue_growth_rates=(0.0,) * 5)
    bull = _flat_assumptions(revenue_growth_rates=(0.05,) * 5)

    scenarios = dcf.run_scenarios(financials, bear, base, bull)

    assert scenarios.bear < scenarios.base < scenarios.bull


def test_wacc_must_exceed_terminal_growth():
    with pytest.raises(ValueError):
        _flat_assumptions(wacc=0.02, terminal_growth=0.05)


def test_growth_rates_length_must_match_forecast_years():
    with pytest.raises(ValueError):
        _flat_assumptions(forecast_years=5, revenue_growth_rates=(0.0, 0.0))
