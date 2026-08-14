"""DB-backed composition layer: pulls fundamentals rows and attaches the
pure reported/derived metrics. This is the layer ai/tools.py and
web/routes_api.py call — they never touch SQL or compute a ratio directly.
"""
from tracker.config import UNIVERSE
from tracker.db.session import get_connection
from tracker.metrics.derived import with_yoy
from tracker.metrics.reported import diluted_share_count, free_cash_flow, with_reported_metrics
from tracker.metrics.valuation import fcf_yield as _fcf_yield
from tracker.metrics.valuation import market_cap as _market_cap


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


def _latest_market_cap(conn, ticker: str) -> dict | None:
    """Latest close x diluted shares for one ticker — the price-side half of
    fcf_yield. Separate from get_valuation() because compare_companies needs
    it for every ticker in the universe, not just one."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, close FROM prices WHERE ticker = %(ticker)s "
            "ORDER BY trade_date DESC LIMIT 1",
            {"ticker": ticker},
        )
        price_row = cur.fetchone()
        cur.execute(
            "SELECT diluted_shares, net_income, eps_diluted FROM fundamentals "
            "WHERE ticker = %(ticker)s ORDER BY fiscal_year DESC LIMIT 1",
            {"ticker": ticker},
        )
        latest_fundamentals_row = cur.fetchone()
    if price_row is None or latest_fundamentals_row is None:
        return None
    price = float(price_row["close"])
    shares = diluted_share_count(latest_fundamentals_row)
    return {
        "price": price,
        "price_as_of": price_row["trade_date"],
        "market_cap": _market_cap(price, shares),
    }


def latest_common_fiscal_year(conn=None) -> int | None:
    """The most recent fiscal year for which every company in UNIVERSE has a
    fundamentals row — the fair, unambiguous choice for an unqualified "last
    year" / "most recent year" in a cross-company comparison.

    The universe's fiscal year ends don't line up (NVDA Jan, MSFT Jun, AAPL
    Sep, GOOGL/ETN Dec), and filers report at different times, so NVDA/MSFT
    can already have a later fiscal_year in `fundamentals` than AAPL/GOOGL/
    ETN. Picking the single overall MAX(fiscal_year) would silently compare
    some companies against a year the others haven't reported yet; this
    takes the latest year common to all five instead. Returns None if any
    tracked ticker has no fundamentals rows at all.
    """
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, MAX(fiscal_year) AS max_fy FROM fundamentals "
                "WHERE ticker = ANY(%(tickers)s) GROUP BY ticker",
                {"tickers": UNIVERSE},
            )
            rows = cur.fetchall()
    finally:
        if owns_conn:
            conn.close()
    if len(rows) < len(UNIVERSE):
        return None
    return min(row["max_fy"] for row in rows)


def compare_companies(metric: str, fiscal_year: int, conn=None) -> list[dict]:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        results = []
        for ticker in UNIVERSE:
            rows = _fetch_fundamentals_rows(conn, ticker)
            enriched = with_yoy([with_reported_metrics(row) for row in rows])
            match = next((r for r in enriched if r["fiscal_year"] == fiscal_year), None)
            if match is None:
                continue
            if metric == "fcf_yield":
                mcap_info = _latest_market_cap(conn, ticker)
                if mcap_info is None or mcap_info["market_cap"] is None:
                    continue
                value = _fcf_yield(free_cash_flow(match), mcap_info["market_cap"])
                if value is None:
                    continue
                results.append({
                    "ticker": ticker,
                    "fiscal_year": fiscal_year,
                    metric: value,
                    "price": mcap_info["price"],
                    "price_as_of": mcap_info["price_as_of"],
                    "market_cap": mcap_info["market_cap"],
                })
            elif match.get(metric) is not None:
                results.append({"ticker": ticker, "fiscal_year": fiscal_year, metric: match[metric]})
        results.sort(key=lambda r: r[metric], reverse=True)
        return results
    finally:
        if owns_conn:
            conn.close()
