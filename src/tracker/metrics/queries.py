"""DB-backed composition layer: pulls fundamentals rows and attaches the
pure reported/derived metrics. This is the layer ai/tools.py and
web/routes_api.py call — they never touch SQL or compute a ratio directly.
"""
from tracker.config import UNIVERSE
from tracker.db.session import get_connection
from tracker.metrics.derived import with_yoy
from tracker.metrics.reported import with_reported_metrics


def _fetch_fundamentals_rows(conn, ticker: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM fundamentals WHERE ticker = %(ticker)s ORDER BY fiscal_year ASC",
            {"ticker": ticker},
        )
        return cur.fetchall()


def get_fundamentals(ticker: str, years: int | None = None, conn=None) -> list[dict]:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        rows = _fetch_fundamentals_rows(conn, ticker)
    finally:
        if owns_conn:
            conn.close()
    enriched = with_yoy([with_reported_metrics(row) for row in rows])
    if years is not None:
        enriched = enriched[-years:]
    return enriched


def compare_companies(metric: str, fiscal_year: int, conn=None) -> list[dict]:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        results = []
        for ticker in UNIVERSE:
            rows = _fetch_fundamentals_rows(conn, ticker)
            enriched = with_yoy([with_reported_metrics(row) for row in rows])
            match = next((r for r in enriched if r["fiscal_year"] == fiscal_year), None)
            if match is not None and match.get(metric) is not None:
                results.append({"ticker": ticker, "fiscal_year": fiscal_year, metric: match[metric]})
        results.sort(key=lambda r: r[metric], reverse=True)
        return results
    finally:
        if owns_conn:
            conn.close()
