"""The own metric: Capex Intensity and Capex Cycle Beta.

Capex Intensity = capex / revenue, per fiscal year — how much of every
revenue dollar a company plows back into physical/compute capacity.

Capex Cycle Beta = (company capex YoY %) / (national capex YoY %), using
FRED's PNFI (Private Nonresidential Fixed Investment) as the macro
denominator. >1 means the company is levering into the capex cycle faster
than the economy around it; <1 means it's lagging or countercyclical.

Known limitation: FRED series are calendar-quarter SAAR observations, so the
macro side is aggregated by calendar year and compared against each
company's fiscal year regardless of fiscal-year-end month (see PLAN.md's
fiscal-year-misalignment note) — a real but small distortion for NVDA (Jan
FYE) and MSFT (Jun FYE).
"""
from tracker.config import FRED_SERIES
from tracker.db.session import get_connection
from tracker.metrics.derived import yoy_growth
from tracker.metrics.queries import get_fundamentals


def capex_intensity(capex: float | None, revenue: float | None) -> float | None:
    if capex is None or not revenue:
        return None
    return float(capex) / float(revenue)


def capex_cycle_beta(company_capex_yoy: float | None, macro_capex_yoy: float | None) -> float | None:
    if company_capex_yoy is None or macro_capex_yoy is None or macro_capex_yoy == 0:
        return None
    return company_capex_yoy / macro_capex_yoy


def _annual_macro_series(conn, series_id: str) -> dict:
    """Calendar-year average of a quarterly SAAR series -> {year: value}."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXTRACT(YEAR FROM obs_date)::int AS year, AVG(value) AS value
            FROM macro_series WHERE series_id = %(series_id)s
            GROUP BY year ORDER BY year
            """,
            {"series_id": series_id},
        )
        return {row["year"]: float(row["value"]) for row in cur.fetchall()}


def get_capex_context(ticker: str, conn=None) -> dict:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        fundamentals = get_fundamentals(ticker, conn=conn)
        macro_annual = _annual_macro_series(conn, FRED_SERIES["capex_anchor"])
    finally:
        if owns_conn:
            conn.close()

    years = sorted(macro_annual)
    macro_yoy_by_year = {
        year: yoy_growth(macro_annual[year], macro_annual.get(year - 1))
        for year in years
    }

    series = []
    prev_capex = None
    for row in fundamentals:
        fy = row["fiscal_year"]
        intensity = capex_intensity(row.get("capex"), row.get("revenue"))
        company_yoy = yoy_growth(row.get("capex"), prev_capex)
        macro_yoy = macro_yoy_by_year.get(fy)
        series.append(
            {
                "fiscal_year": fy,
                "capex": row.get("capex"),
                "revenue": row.get("revenue"),
                "capex_intensity": intensity,
                "capex_yoy": company_yoy,
                "macro_capex_yoy": macro_yoy,
                "capex_cycle_beta": capex_cycle_beta(company_yoy, macro_yoy),
            }
        )
        prev_capex = row.get("capex")

    return {"ticker": ticker, "series": series, "macro_series_id": FRED_SERIES["capex_anchor"]}
