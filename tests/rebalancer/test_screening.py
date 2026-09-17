from __future__ import annotations

from rebalancer.screening import (
    ScreeningCriteria,
    StockProfile,
    passes_disqualification_filter,
    passes_quality_filter,
    passes_valuation_prefilter,
    screen_universe,
)


def _good_stock(**overrides) -> StockProfile:
    defaults = dict(
        ticker="000000",
        is_managed_issue=False,
        is_trading_halted=False,
        is_spac=False,
        is_preferred_share=False,
        audit_opinion="적정",
        market_cap=200_000_000_000,
        avg_daily_trading_value=1_000_000_000,
        debt_ratio=0.8,
        interest_coverage_ratio=5.0,
        consecutive_profit_years=5,
        valuation_percentile=0.1,
    )
    defaults.update(overrides)
    return StockProfile(**defaults)


def test_passes_disqualification_filter_for_clean_stock():
    assert passes_disqualification_filter(_good_stock()) is True


def test_managed_issue_is_disqualified():
    assert passes_disqualification_filter(_good_stock(is_managed_issue=True)) is False


def test_trading_halted_is_disqualified():
    assert passes_disqualification_filter(_good_stock(is_trading_halted=True)) is False


def test_spac_is_disqualified():
    assert passes_disqualification_filter(_good_stock(is_spac=True)) is False


def test_preferred_share_is_disqualified():
    assert passes_disqualification_filter(_good_stock(is_preferred_share=True)) is False


def test_non_clean_audit_opinion_is_disqualified():
    assert passes_disqualification_filter(_good_stock(audit_opinion="한정")) is False


def test_quality_filter_rejects_small_illiquid_stock():
    criteria = ScreeningCriteria()
    small_cap = _good_stock(market_cap=10_000_000_000)
    assert passes_quality_filter(small_cap, criteria) is False


def test_quality_filter_rejects_over_leveraged_stock():
    criteria = ScreeningCriteria()
    over_leveraged = _good_stock(debt_ratio=5.0)
    assert passes_quality_filter(over_leveraged, criteria) is False


def test_quality_filter_rejects_recent_loss_maker():
    criteria = ScreeningCriteria()
    recent_loss = _good_stock(consecutive_profit_years=1)
    assert passes_quality_filter(recent_loss, criteria) is False


def test_valuation_prefilter_rejects_expensive_stock():
    criteria = ScreeningCriteria(valuation_percentile_max=0.3)
    expensive = _good_stock(valuation_percentile=0.9)
    assert passes_valuation_prefilter(expensive, criteria) is False


def test_screen_universe_chains_all_filters():
    stocks = [
        _good_stock(ticker="A"),
        _good_stock(ticker="B", is_managed_issue=True),
        _good_stock(ticker="C", debt_ratio=5.0),
        _good_stock(ticker="D", valuation_percentile=0.9),
    ]

    survivors = screen_universe(stocks)

    assert [s.ticker for s in survivors] == ["A"]
