"""Unit tests for the XBRL tag fallback chain resolution — pure Python, no DB."""
from tracker.transform.normalize import normalize_facts, resolve_concept_for_fy


def _fact(concept, unit, fy, value, filed, accn="0001-24-000001", period_end="2024-12-31"):
    return {
        "concept": concept,
        "unit": unit,
        "fy": fy,
        "value": value,
        "filed": filed,
        "accn": accn,
        "period_end": period_end,
    }


def test_first_tag_in_chain_wins_when_present():
    facts = [
        _fact("RevenueFromContractWithCustomerExcludingAssessedTax", "USD", 2024, 100, "2025-01-01"),
        _fact("Revenues", "USD", 2024, 999, "2025-01-01"),
    ]
    tag, fact = resolve_concept_for_fy(facts, "revenue", 2024)
    assert tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert fact["value"] == 100


def test_falls_back_to_next_tag_when_first_absent():
    facts = [_fact("Revenues", "USD", 2024, 500, "2025-01-01")]
    tag, fact = resolve_concept_for_fy(facts, "revenue", 2024)
    assert tag == "Revenues"
    assert fact["value"] == 500


def test_no_matching_tag_returns_none():
    facts = [_fact("Revenues", "USD", 2023, 500, "2024-01-01")]
    tag, fact = resolve_concept_for_fy(facts, "revenue", 2024)
    assert tag is None
    assert fact is None


def test_restatement_latest_filed_wins():
    facts = [
        _fact("Revenues", "USD", 2024, 100, "2025-01-01"),
        _fact("Revenues", "USD", 2024, 105, "2025-06-01"),  # restated later
    ]
    tag, fact = resolve_concept_for_fy(facts, "revenue", 2024)
    assert fact["value"] == 105


def test_unit_mismatch_is_ignored():
    facts = [_fact("EarningsPerShareDiluted", "USD", 2024, 1.23, "2025-01-01")]
    tag, fact = resolve_concept_for_fy(facts, "eps_diluted", 2024)
    assert tag is None  # wrong unit (should be USD/shares)


def test_normalize_facts_builds_one_row_per_fiscal_year():
    facts = [
        _fact("Revenues", "USD", 2023, 100, "2024-01-01", period_end="2023-12-31"),
        _fact("NetIncomeLoss", "USD", 2023, 10, "2024-01-01", period_end="2023-12-31"),
        _fact("Revenues", "USD", 2024, 200, "2025-01-01", period_end="2024-12-31"),
        _fact("NetIncomeLoss", "USD", 2024, 20, "2025-01-01", period_end="2024-12-31"),
    ]
    rows = normalize_facts(facts)
    assert [r["fiscal_year"] for r in rows] == [2023, 2024]
    assert rows[0]["revenue"] == 100
    assert rows[0]["revenue_tag"] == "Revenues"
    assert rows[1]["net_income"] == 20


def test_normalize_facts_skips_fiscal_years_with_no_recognized_concepts():
    facts = [_fact("SomeUnrelatedConcept", "USD", 2024, 1, "2025-01-01")]
    rows = normalize_facts(facts)
    assert rows == []


def test_normalize_facts_leaves_missing_concepts_null():
    facts = [_fact("Revenues", "USD", 2024, 200, "2025-01-01")]
    rows = normalize_facts(facts)
    assert rows[0]["revenue"] == 200
    assert rows[0]["net_income"] is None
    assert rows[0]["net_income_tag"] is None


def test_normalize_facts_derives_gross_profit_when_no_subtotal_reported():
    # GOOGL/ETN-style filers: no GrossProfit tag, but CostOfRevenue is present.
    facts = [
        _fact("Revenues", "USD", 2024, 350018, "2025-01-01"),
        _fact("CostOfRevenue", "USD", 2024, 146306, "2025-01-01"),
    ]
    rows = normalize_facts(facts)
    assert rows[0]["gross_profit"] == 350018 - 146306
    assert rows[0]["gross_profit_tag"] == "derived:revenue-CostOfRevenue"


def test_nonoperating_income_prefers_aggregate_line_over_narrow_equity_tag():
    # The aggregate "Other income (expense), net" line reflects the real
    # non-operating swing; the narrower ASC 321 equity-securities note tag
    # can materially understate it even when both are present for the same
    # filer (see concepts.py's nonoperating_income chain comment).
    facts = [
        _fact("EquitySecuritiesFvNiUnrealizedGainLoss", "USD", 2024, 1_907, "2025-01-01"),
        _fact("NonoperatingIncomeExpense", "USD", 2024, 29_787, "2025-01-01"),
    ]
    tag, fact = resolve_concept_for_fy(facts, "nonoperating_income", 2024)
    assert tag == "NonoperatingIncomeExpense"
    assert fact["value"] == 29_787


def test_nonoperating_income_falls_back_to_narrow_tag_when_aggregate_absent():
    facts = [_fact("EquitySecuritiesFvNiUnrealizedGainLoss", "USD", 2024, 1_907, "2025-01-01")]
    tag, fact = resolve_concept_for_fy(facts, "nonoperating_income", 2024)
    assert tag == "EquitySecuritiesFvNiUnrealizedGainLoss"
    assert fact["value"] == 1_907


def test_normalize_facts_prefers_reported_gross_profit_over_derived():
    facts = [
        _fact("Revenues", "USD", 2024, 350018, "2025-01-01"),
        _fact("CostOfRevenue", "USD", 2024, 146306, "2025-01-01"),
        _fact("GrossProfit", "USD", 2024, 999, "2025-01-01"),
    ]
    rows = normalize_facts(facts)
    assert rows[0]["gross_profit"] == 999
    assert rows[0]["gross_profit_tag"] == "GrossProfit"
