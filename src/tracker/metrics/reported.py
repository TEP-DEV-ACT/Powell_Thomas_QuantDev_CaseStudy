"""Pure functions over a single fundamentals row (dict-like with revenue,
net_income, eps_diluted, gross_profit, operating_income, capex,
operating_cash_flow). No DB access here — see db_reads.py for the query
layer that hands these functions their input.
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


def with_reported_metrics(row: dict) -> dict:
    return {
        **row,
        "gross_margin": gross_margin(row),
        "operating_margin": operating_margin(row),
        "free_cash_flow": free_cash_flow(row),
    }
