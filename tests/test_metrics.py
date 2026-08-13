"""Hand-checked fixtures for the pure metrics functions."""
from tracker.metrics.capex import capex_cycle_beta, capex_intensity
from tracker.metrics.derived import margin_delta_bps, with_yoy, yoy_growth
from tracker.metrics.reported import free_cash_flow, gross_margin, operating_margin, with_reported_metrics
from tracker.metrics.valuation import price_to_sales, trailing_pe


def test_gross_margin():
    assert gross_margin({"gross_profit": 25, "revenue": 100}) == 0.25


def test_gross_margin_missing_inputs():
    assert gross_margin({"gross_profit": None, "revenue": 100}) is None
    assert gross_margin({"gross_profit": 25, "revenue": 0}) is None


def test_operating_margin():
    assert operating_margin({"operating_income": 15, "revenue": 100}) == 0.15


def test_free_cash_flow():
    assert free_cash_flow({"operating_cash_flow": 120, "capex": 30}) == 90


def test_with_reported_metrics_attaches_all_three():
    row = {"revenue": 391035, "gross_profit": 180683, "operating_income": 123216,
           "operating_cash_flow": 118254, "capex": 9447}
    enriched = with_reported_metrics(row)
    assert round(enriched["gross_margin"], 4) == round(180683 / 391035, 4)
    assert round(enriched["operating_margin"], 4) == round(123216 / 391035, 4)
    assert enriched["free_cash_flow"] == 118254 - 9447


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


def test_capex_intensity():
    assert capex_intensity(9447, 391035) == 9447 / 391035
    assert capex_intensity(None, 391035) is None
    assert capex_intensity(9447, 0) is None


def test_capex_cycle_beta():
    # company capex growing 20% while the macro anchor grows 10% -> beta 2.0
    assert capex_cycle_beta(0.20, 0.10) == 2.0
    assert capex_cycle_beta(0.20, None) is None
    assert capex_cycle_beta(0.20, 0) is None
