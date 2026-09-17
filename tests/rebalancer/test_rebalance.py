from __future__ import annotations

from rebalancer.rebalance import RebalanceAction, compute_rebalance_orders


def test_small_drift_within_band_is_hold():
    orders = compute_rebalance_orders({"A": 0.20}, {"A": 0.22}, band=0.05)

    assert orders[0].action == RebalanceAction.HOLD


def test_positive_drift_beyond_band_is_buy():
    orders = compute_rebalance_orders({"A": 0.10}, {"A": 0.25}, band=0.05)

    assert orders[0].action == RebalanceAction.BUY
    assert orders[0].drift == 0.15


def test_negative_drift_beyond_band_is_sell():
    orders = compute_rebalance_orders({"A": 0.30}, {"A": 0.10}, band=0.05)

    assert orders[0].action == RebalanceAction.SELL


def test_new_target_ticker_not_currently_held_is_buy():
    orders = compute_rebalance_orders({}, {"A": 0.20}, band=0.05)

    assert orders[0].current_weight == 0.0
    assert orders[0].action == RebalanceAction.BUY


def test_ticker_dropped_from_target_is_sell():
    orders = compute_rebalance_orders({"A": 0.20}, {}, band=0.05)

    assert orders[0].target_weight == 0.0
    assert orders[0].action == RebalanceAction.SELL


def test_orders_sorted_by_ticker():
    orders = compute_rebalance_orders(
        {"C": 0.1, "A": 0.1}, {"C": 0.3, "A": 0.3, "B": 0.4}, band=0.05
    )

    assert [order.ticker for order in orders] == ["A", "B", "C"]
