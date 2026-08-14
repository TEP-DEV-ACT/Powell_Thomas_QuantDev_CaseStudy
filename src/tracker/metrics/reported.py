"""Pure functions over a single fundamentals row (dict-like with revenue,
net_income, eps_diluted, diluted_shares, gross_profit, operating_income,
capex, operating_cash_flow). No DB access here — see db_reads.py for the
query layer that hands these functions their input.

Cross-company comparison uses margins/yield (net_income_margin, fcf_margin,
fcf_yield, gross_margin, operating_margin), not per-share figures — EDGAR
does not retroactively re-tag diluted share counts for stock splits
(GOOGL 20:1 in 2022, NVDA 10:1 in FY2025, AAPL 4:1 in 2020), so a per-share
series steps sharply at each split year, while margins are immune.
"""


def gross_margin(row: dict) -> float | None:
    if row.get("gross_profit") is None or not row.get("revenue"):
        return None
    return float(row["gross_profit"]) / float(row["revenue"])


def operating_margin(row: dict) -> float | None:
    if row.get("operating_income") is None or not row.get("revenue"):
        return None
    return float(row["operating_income"]) / float(row["revenue"])


def free_cash_flow(row: dict) -> float | None:
    if row.get("operating_cash_flow") is None or row.get("capex") is None:
        return None
    return float(row["operating_cash_flow"]) - float(row["capex"])


def net_income_margin(row: dict) -> float | None:
    if row.get("net_income") is None or not row.get("revenue"):
        return None
    return float(row["net_income"]) / float(row["revenue"])


def fcf_margin(row: dict) -> float | None:
    fcf = free_cash_flow(row)
    if fcf is None or not row.get("revenue"):
        return None
    return fcf / float(row["revenue"])


def adjusted_net_income_margin(row: dict) -> float | None:
    adj = adjusted_net_income(row)
    if adj is None or not row.get("revenue"):
        return None
    return adj / float(row["revenue"])


def other_income_adjustments(row: dict) -> float | None:
    """The non-operating income/expense embedded in reported net income — the
    as-reported "Other income (expense), net" line (see concepts.py), which
    also bundles in interest income/expense for companies that don't tag the
    two separately — a known precision gap, not a pure investment-marks
    isolate. This is the pre-tax, as-filed figure; adjusted_net_income()
    tax-effects it before backing it out. None (not zero) when no tag in the
    chain matched that fiscal year, so a real gap in the source data isn't
    drawn as "no effect."
    """
    value = row.get("nonoperating_income")
    return float(value) if value is not None else None


def effective_tax_rate(row: dict) -> float | None:
    """income_tax_expense / pretax_income for the fiscal year, where pretax
    income is derived as net_income + income_tax_expense (both as-reported,
    after-tax and tax-expense XBRL figures). Used to tax-effect
    other_income_adjustments in adjusted_net_income() — the reported
    nonoperating_income line is pre-tax, so subtracting it whole from
    after-tax net_income would overstate its impact. None when either input
    is missing or the implied pretax income isn't positive (rate undefined).
    """
    tax = row.get("income_tax_expense")
    net_income = row.get("net_income")
    if tax is None or net_income is None:
        return None
    pretax = float(net_income) + float(tax)
    if pretax <= 0:
        return None
    return float(tax) / pretax


def adjusted_net_income(row: dict) -> float | None:
    """Net income with other_income_adjustments backed out at the company's
    own effective tax rate for the year, so a swing driven by an investment
    mark-to-market (or interest income/expense, per the tag-precision gap
    above) doesn't read as a change in operating performance. Tax-effecting
    matters because other_income_adjustments is pre-tax while net_income is
    after-tax; without it the adjustment overstates its own impact. None
    when net_income, the adjustment, or the effective tax rate is unknown —
    see other_income_adjustments() and effective_tax_rate().
    """
    adjustment = other_income_adjustments(row)
    rate = effective_tax_rate(row)
    if row.get("net_income") is None or adjustment is None or rate is None:
        return None
    return float(row["net_income"]) - adjustment * (1 - rate)


def diluted_share_count(row: dict) -> float | None:
    """Diluted shares for the fiscal year, falling back to net_income / EPS.

    GOOGL only tags WeightedAverageNumberOfDilutedSharesOutstanding from
    FY2024 onwards, so the stored column is null for FY2015-2023 and it would
    otherwise drop out of every per-share comparison for those years. Where
    both are present the implied count agrees to within ~0.05% (GOOGL FY2024:
    12,452.5M implied vs 12,447M reported), so it is a safe stand-in.

    That same net_income/EPS-implied count also guards against a known SEC
    XBRL scaling glitch on some early-2010s filings: NVDA's FY2010
    WeightedAverageNumberOfDilutedSharesOutstanding fact is filed as 588,684
    instead of ~588,684,000 (confirmed against data.sec.gov's own
    companyconcept API — this is SEC's own filed data, not an ingestion
    bug). When the reported count and the implied count disagree by more
    than 100x, the reported count is untrustworthy and the implied count is
    used instead.

    Note these are as-reported counts — EDGAR does not retroactively re-tag
    for stock splits, so the series steps at a split just as EPS does.
    """
    shares = row.get("diluted_shares")
    net_income, eps = row.get("net_income"), row.get("eps_diluted")
    implied = float(net_income) / float(eps) if net_income is not None and eps else None
    if shares:
        shares = float(shares)
        ratio = implied / shares if implied is not None else None
        if ratio is not None and not (0.01 <= ratio <= 100):
            return implied
        return shares
    return implied


def with_reported_metrics(row: dict) -> dict:
    return {
        **row,
        "gross_margin": gross_margin(row),
        "operating_margin": operating_margin(row),
        "net_income_margin": net_income_margin(row),
        "fcf_margin": fcf_margin(row),
        "free_cash_flow": free_cash_flow(row),
        "other_income_adjustments": other_income_adjustments(row),
        "effective_tax_rate": effective_tax_rate(row),
        "adjusted_net_income": adjusted_net_income(row),
        "adjusted_net_income_margin": adjusted_net_income_margin(row),
    }
