"""Pure functions over a single fundamentals row (dict-like with revenue,
net_income, eps_diluted, diluted_shares, gross_profit, operating_income,
capex, operating_cash_flow). No DB access here — see db_reads.py for the
query layer that hands these functions their input.

Per-share variants exist because absolute revenue/net income/FCF rank the
tracked companies by sheer size, which makes a cross-company comparison
uninformative. Dividing by the diluted share count puts all five on a
common footing.
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


def diluted_share_count(row: dict) -> float | None:
    """Diluted shares for the fiscal year, falling back to net_income / EPS.

    GOOGL only tags WeightedAverageNumberOfDilutedSharesOutstanding from
    FY2024 onwards, so the stored column is null for FY2015-2023 and it would
    otherwise drop out of every per-share comparison for those years. Where
    both are present the implied count agrees to within ~0.05% (GOOGL FY2024:
    12,452.5M implied vs 12,447M reported), so it is a safe stand-in.

    Note these are as-reported counts — EDGAR does not retroactively re-tag
    for stock splits, so the series steps at a split just as EPS does.
    """
    shares = row.get("diluted_shares")
    if shares:
        return float(shares)
    net_income, eps = row.get("net_income"), row.get("eps_diluted")
    if net_income is None or not eps:
        return None
    return float(net_income) / float(eps)


def _per_share(value: float | None, shares: float | None) -> float | None:
    if value is None or not shares:
        return None
    return float(value) / float(shares)


def revenue_per_share(row: dict) -> float | None:
    return _per_share(row.get("revenue"), diluted_share_count(row))


def net_income_per_share(row: dict) -> float | None:
    return _per_share(row.get("net_income"), diluted_share_count(row))


def fcf_per_share(row: dict) -> float | None:
    return _per_share(free_cash_flow(row), diluted_share_count(row))


def with_reported_metrics(row: dict) -> dict:
    return {
        **row,
        "gross_margin": gross_margin(row),
        "operating_margin": operating_margin(row),
        "free_cash_flow": free_cash_flow(row),
        "revenue_per_share": revenue_per_share(row),
        "net_income_per_share": net_income_per_share(row),
        "fcf_per_share": fcf_per_share(row),
    }
