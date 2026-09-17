"""잔여이익모델(Residual Income Model, RIM).

금융업/지주회사처럼 FCF 개념이 사업 실질을 왜곡하는 업종에 적용한다
(docs/rebalancer-design.md §3 참조). 현재 순자산(BPS)에서 출발해 초과이익의
현재가치를 더하는 구조라 DCF보다 영구가치(terminal value) 의존도가 낮다.

검산 포인트: ROE가 매 기간 자기자본비용과 같으면 잔여이익이 0이 되어
내재가치가 그대로 BPS와 같아야 한다 (초과수익이 없으면 장부가가 곧 적정가).
"""

from __future__ import annotations

from rebalancer.models import FinancialSnapshot, RIMAssumptions


def intrinsic_value_per_share(
    financials: FinancialSnapshot, assumptions: RIMAssumptions
) -> float:
    book_value_per_share = financials.total_equity / financials.shares_outstanding
    cost_of_equity = assumptions.cost_of_equity

    present_value_of_residual_income = 0.0
    book_value = book_value_per_share
    last_residual_income = 0.0
    for year_index, roe in enumerate(assumptions.roe_path, start=1):
        eps = roe * book_value
        residual_income = eps - cost_of_equity * book_value
        present_value_of_residual_income += residual_income / (
            1 + cost_of_equity
        ) ** year_index

        dividend = eps * assumptions.payout_ratio
        book_value += eps - dividend
        last_residual_income = residual_income

    terminal_residual_income_value = (
        last_residual_income
        * (1 + assumptions.terminal_growth)
        / (cost_of_equity - assumptions.terminal_growth)
    )
    present_value_of_terminal = terminal_residual_income_value / (
        1 + cost_of_equity
    ) ** assumptions.forecast_years

    return (
        book_value_per_share
        + present_value_of_residual_income
        + present_value_of_terminal
    )
