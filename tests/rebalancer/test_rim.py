from __future__ import annotations

import pytest

from rebalancer.models import FinancialSnapshot, RIMAssumptions
from rebalancer.valuation import rim


def _financials(total_equity: float = 1000.0, shares: float = 100.0) -> FinancialSnapshot:
    return FinancialSnapshot(
        fiscal_year=2025,
        revenue=0.0,
        operating_margin=0.0,
        tax_rate=0.0,
        total_equity=total_equity,
        net_debt=0.0,
        shares_outstanding=shares,
    )


def test_roe_equals_cost_of_equity_gives_intrinsic_value_equal_to_book_value():
    """초과수익(ROE - COE)이 0이면 잔여이익도 0 → 내재가치는 그대로 BPS."""
    financials = _financials(total_equity=1000.0, shares=100.0)
    assumptions = RIMAssumptions(
        forecast_years=5,
        roe_path=(0.10, 0.10, 0.10, 0.10, 0.10),
        cost_of_equity=0.10,
        terminal_growth=0.02,
    )

    value = rim.intrinsic_value_per_share(financials, assumptions)

    assert value == pytest.approx(10.0, rel=1e-9)


def test_roe_above_cost_of_equity_gives_premium_to_book_value():
    financials = _financials(total_equity=1000.0, shares=100.0)
    assumptions = RIMAssumptions(
        forecast_years=5,
        roe_path=(0.18, 0.18, 0.18, 0.18, 0.18),
        cost_of_equity=0.10,
        terminal_growth=0.02,
    )

    value = rim.intrinsic_value_per_share(financials, assumptions)

    assert value > 10.0


def test_roe_below_cost_of_equity_gives_discount_to_book_value():
    financials = _financials(total_equity=1000.0, shares=100.0)
    assumptions = RIMAssumptions(
        forecast_years=5,
        roe_path=(0.04, 0.04, 0.04, 0.04, 0.04),
        cost_of_equity=0.10,
        terminal_growth=0.02,
    )

    value = rim.intrinsic_value_per_share(financials, assumptions)

    assert value < 10.0


def test_cost_of_equity_must_exceed_terminal_growth():
    with pytest.raises(ValueError):
        RIMAssumptions(
            forecast_years=3,
            roe_path=(0.1, 0.1, 0.1),
            cost_of_equity=0.03,
            terminal_growth=0.05,
        )


def test_roe_path_length_must_match_forecast_years():
    with pytest.raises(ValueError):
        RIMAssumptions(
            forecast_years=3,
            roe_path=(0.1, 0.1),
            cost_of_equity=0.10,
            terminal_growth=0.02,
        )
