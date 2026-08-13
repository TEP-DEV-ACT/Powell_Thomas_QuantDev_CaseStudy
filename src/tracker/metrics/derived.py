"""Pure YoY-growth and margin-delta functions, applied across a fiscal-year-
ordered series of reported rows.
"""

YOY_FIELDS = ["revenue", "net_income", "eps_diluted", "free_cash_flow"]
MARGIN_FIELDS = ["gross_margin", "operating_margin"]


def yoy_growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (float(current) - float(previous)) / abs(float(previous))


def margin_delta_bps(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return (float(current) - float(previous)) * 10_000


def with_yoy(rows_asc: list[dict]) -> list[dict]:
    """rows_asc must be sorted ascending by fiscal_year."""
    out = []
    prev = None
    for row in rows_asc:
        enriched = dict(row)
        for field in YOY_FIELDS:
            enriched[f"{field}_yoy"] = yoy_growth(row.get(field), prev.get(field)) if prev else None
        for field in MARGIN_FIELDS:
            enriched[f"{field}_delta_bps"] = margin_delta_bps(row.get(field), prev.get(field)) if prev else None
        out.append(enriched)
        prev = row
    return out
