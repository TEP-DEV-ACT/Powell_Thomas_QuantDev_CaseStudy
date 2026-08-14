"""Hand-checked fixtures for the pure metrics functions."""
from tracker.metrics.capex import capex_cycle_beta, capex_intensity
from tracker.metrics.derived import margin_delta_bps, with_yoy, yoy_growth
from tracker.metrics.reported import (
    adjusted_net_income,
    adjusted_net_income_margin,
    diluted_share_count,
    effective_tax_rate,
    fcf_margin,
    fcf_per_share,
    free_cash_flow,
    gross_margin,
    net_income_margin,
    net_income_per_share,
    operating_margin,
    other_income_adjustments,
    revenue_per_share,
    with_reported_metrics,
)
from tracker.metrics.valuation import fcf_yield, market_cap, price_to_sales, trailing_pe


def test_gross_margin():
    assert gross_margin({"gross_profit": 25, "revenue": 100}) == 0.25


def test_gross_margin_missing_inputs():
    assert gross_margin({"gross_profit": None, "revenue": 100}) is None
    assert gross_margin({"gross_profit": 25, "revenue": 0}) is None


def test_operating_margin():
    assert operating_margin({"operating_income": 15, "revenue": 100}) == 0.15


def test_free_cash_flow():
    assert free_cash_flow({"operating_cash_flow": 120, "capex": 30}) == 90


def test_net_income_margin():
    assert net_income_margin({"net_income": 24, "revenue": 100}) == 0.24


def test_net_income_margin_missing_inputs():
    assert net_income_margin({"net_income": None, "revenue": 100}) is None
    assert net_income_margin({"net_income": 24, "revenue": 0}) is None


def test_fcf_margin():
    row = {"operating_cash_flow": 120, "capex": 20, "revenue": 500}
    assert fcf_margin(row) == 100 / 500


def test_fcf_margin_missing_inputs():
    assert fcf_margin({"operating_cash_flow": None, "capex": 20, "revenue": 500}) is None
    assert fcf_margin({"operating_cash_flow": 120, "capex": 20, "revenue": 0}) is None


def test_other_income_adjustments():
    assert other_income_adjustments({"nonoperating_income": 500}) == 500.0
    # A loss (negative) passes through as-is, not clamped to zero.
    assert other_income_adjustments({"nonoperating_income": -300}) == -300.0


def test_other_income_adjustments_missing_tag_is_none_not_zero():
    assert other_income_adjustments({"nonoperating_income": None}) is None
    assert other_income_adjustments({}) is None


def test_effective_tax_rate():
    # tax=2,500 on pretax income of 7,500+2,500=10,000 -> 25% effective rate.
    assert effective_tax_rate({"net_income": 7_500, "income_tax_expense": 2_500}) == 0.25


def test_effective_tax_rate_missing_inputs():
    assert effective_tax_rate({"net_income": None, "income_tax_expense": 2_500}) is None
    assert effective_tax_rate({"net_income": 7_500, "income_tax_expense": None}) is None


def test_effective_tax_rate_nonpositive_pretax_income_is_none():
    # net_income + income_tax_expense <= 0 -> rate is undefined, not a
    # divide-by-zero or a misleading negative/huge number.
    assert effective_tax_rate({"net_income": -2_500, "income_tax_expense": 2_500}) is None
    assert effective_tax_rate({"net_income": -3_000, "income_tax_expense": 1_000}) is None


def test_adjusted_net_income_backs_out_a_gain_after_tax():
    # A $500 pre-tax investment-marks gain at a 25% effective rate is worth
    # $375 after tax; adjusted removes only that after-tax amount.
    row = {"net_income": 7_500, "income_tax_expense": 2_500, "nonoperating_income": 500}
    assert adjusted_net_income(row) == 7_500 - 375


def test_adjusted_net_income_backs_out_a_loss_after_tax():
    # A $300 pre-tax loss at a 25% effective rate is a $225 after-tax hit
    # that suppressed net income; adjusted adds back only that amount.
    row = {"net_income": 7_500, "income_tax_expense": 2_500, "nonoperating_income": -300}
    assert adjusted_net_income(row) == 7_500 + 225


def test_adjusted_net_income_missing_inputs():
    base = {"net_income": 7_500, "income_tax_expense": 2_500, "nonoperating_income": 500}
    assert adjusted_net_income({**base, "net_income": None}) is None
    assert adjusted_net_income({**base, "nonoperating_income": None}) is None
    # No income_tax_expense tag -> no effective rate -> can't tax-effect, so
    # the whole adjustment is None rather than silently falling back to a
    # pre-tax subtraction.
    assert adjusted_net_income({**base, "income_tax_expense": None}) is None


def test_adjusted_net_income_margin():
    row = {"net_income": 7_500, "income_tax_expense": 2_500, "nonoperating_income": 500, "revenue": 100_000}
    assert round(adjusted_net_income_margin(row), 5) == round((7_500 - 375) / 100_000, 5)


def test_adjusted_net_income_margin_missing_inputs():
    row = {"net_income": 7_500, "income_tax_expense": 2_500, "nonoperating_income": 500}
    assert adjusted_net_income_margin({**row, "revenue": 0}) is None
    assert adjusted_net_income_margin({**row, "revenue": 100_000, "net_income": None}) is None


def test_with_reported_metrics_attaches_all_three():
    row = {"revenue": 391035, "gross_profit": 180683, "operating_income": 123216,
           "net_income": 93736, "operating_cash_flow": 118254, "capex": 9447}
    enriched = with_reported_metrics(row)
    assert round(enriched["gross_margin"], 4) == round(180683 / 391035, 4)
    assert round(enriched["operating_margin"], 4) == round(123216 / 391035, 4)
    assert round(enriched["net_income_margin"], 4) == round(93736 / 391035, 4)
    assert enriched["free_cash_flow"] == 118254 - 9447
    assert round(enriched["fcf_margin"], 4) == round((118254 - 9447) / 391035, 4)


def test_diluted_share_count_prefers_the_reported_column():
    assert diluted_share_count({"diluted_shares": 1000, "net_income": 50, "eps_diluted": 0.1}) == 1000


def test_diluted_share_count_falls_back_to_net_income_over_eps():
    # GOOGL FY2015-2023 has no WeightedAverageNumberOfDilutedSharesOutstanding tag
    assert diluted_share_count({"diluted_shares": None, "net_income": 100, "eps_diluted": 0.5}) == 200


def test_diluted_share_count_missing_inputs():
    assert diluted_share_count({"diluted_shares": None, "net_income": 100, "eps_diluted": None}) is None
    assert diluted_share_count({"diluted_shares": None, "net_income": 100, "eps_diluted": 0}) is None
    assert diluted_share_count({"diluted_shares": 0, "net_income": None, "eps_diluted": 2}) is None


def test_per_share_metrics():
    row = {"revenue": 1000, "net_income": 100, "diluted_shares": 50,
           "operating_cash_flow": 120, "capex": 20}
    assert revenue_per_share(row) == 20.0
    assert net_income_per_share(row) == 2.0
    assert fcf_per_share(row) == 2.0  # (120 - 20) / 50


def test_per_share_metrics_missing_inputs():
    assert revenue_per_share({"revenue": 1000, "diluted_shares": None}) is None
    assert revenue_per_share({"revenue": None, "diluted_shares": 50}) is None
    # no capex -> no FCF -> no FCF per share, even though shares are known
    assert fcf_per_share({"operating_cash_flow": 120, "capex": None, "diluted_shares": 50}) is None


def test_with_reported_metrics_attaches_per_share():
    row = {"revenue": 391035, "net_income": 93736, "diluted_shares": 15408,
           "operating_cash_flow": 118254, "capex": 9447}
    enriched = with_reported_metrics(row)
    assert round(enriched["revenue_per_share"], 4) == round(391035 / 15408, 4)
    assert round(enriched["net_income_per_share"], 4) == round(93736 / 15408, 4)
    assert round(enriched["fcf_per_share"], 4) == round((118254 - 9447) / 15408, 4)


def test_yoy_growth():
    assert yoy_growth(110, 100) == 0.1
    assert yoy_growth(90, 100) == -0.1


def test_yoy_growth_handles_missing_or_zero_prior():
    assert yoy_growth(110, None) is None
    assert yoy_growth(110, 0) is None


def test_margin_delta_bps():
    assert round(margin_delta_bps(0.26, 0.25), 6) == 100.0


def test_with_yoy_across_series():
    rows = [
        {"fiscal_year": 2023, "revenue": 100, "net_income": 10, "eps_diluted": 1.0,
         "free_cash_flow": 20, "gross_margin": 0.5, "operating_margin": 0.2},
        {"fiscal_year": 2024, "revenue": 120, "net_income": 12, "eps_diluted": 1.2,
         "free_cash_flow": 25, "gross_margin": 0.55, "operating_margin": 0.22},
    ]
    enriched = with_yoy(rows)
    assert enriched[0]["revenue_yoy"] is None  # no prior year
    assert round(enriched[1]["revenue_yoy"], 4) == 0.2
    assert round(enriched[1]["gross_margin_delta_bps"], 2) == 500.0


def test_trailing_pe():
    assert round(trailing_pe(220.0, 11.93), 2) == round(220.0 / 11.93, 2)
    assert trailing_pe(220.0, None) is None
    assert trailing_pe(220.0, 0) is None


def test_price_to_sales():
    # price=100, shares=1000 -> market cap 100,000; revenue=50,000 -> P/S = 2.0
    assert price_to_sales(100.0, 1000, 50_000) == 2.0
    assert price_to_sales(100.0, 1000, 0) is None


def test_market_cap():
    assert market_cap(100.0, 1000) == 100_000.0
    assert market_cap(100.0, None) is None
    assert market_cap(100.0, 0) is None
    assert market_cap(None, 1000) is None


def test_fcf_yield():
    # fcf=5,000, market_cap=100,000 -> yield 5%
    assert fcf_yield(5_000, 100_000) == 0.05
    assert fcf_yield(None, 100_000) is None
    assert fcf_yield(5_000, 0) is None
    assert fcf_yield(5_000, None) is None


def test_capex_intensity():
    assert capex_intensity(9447, 391035) == 9447 / 391035
    assert capex_intensity(None, 391035) is None
    assert capex_intensity(9447, 0) is None


def test_capex_cycle_beta():
    # company capex growing 20% while the macro anchor grows 10% -> beta 2.0
    assert capex_cycle_beta(0.20, 0.10) == 2.0
    assert capex_cycle_beta(0.20, None) is None
    assert capex_cycle_beta(0.20, 0) is None
