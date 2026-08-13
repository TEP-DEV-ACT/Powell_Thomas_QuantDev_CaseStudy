"""Cross-source metrics: joins the latest market price against the latest
reported annual fundamentals. Both are explicitly trailing — the as-of dates
are always returned alongside the ratio so a caller can see how stale the
EPS/revenue figure is relative to the live-ish price.
"""
from tracker.db.session import get_connection


def trailing_pe(price: float | None, eps_diluted: float | None) -> float | None:
    if price is None or eps_diluted is None or eps_diluted == 0:
        return None
    return float(price) / float(eps_diluted)


def price_to_sales(price: float | None, diluted_shares: float | None, revenue: float | None) -> float | None:
    if price is None or diluted_shares is None or not revenue:
        return None
    return (float(price) * float(diluted_shares)) / float(revenue)


def get_valuation(ticker: str, conn=None) -> dict | None:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date, close FROM prices WHERE ticker = %(ticker)s ORDER BY trade_date DESC LIMIT 1",
                {"ticker": ticker},
            )
            price_row = cur.fetchone()

            cur.execute(
                """
                SELECT fiscal_year, period_end, eps_diluted, diluted_shares, revenue
                FROM fundamentals WHERE ticker = %(ticker)s
                ORDER BY fiscal_year DESC LIMIT 1
                """,
                {"ticker": ticker},
            )
            fundamentals_row = cur.fetchone()
    finally:
        if owns_conn:
            conn.close()

    if price_row is None or fundamentals_row is None:
        return None

    price = float(price_row["close"])
    eps = float(fundamentals_row["eps_diluted"]) if fundamentals_row["eps_diluted"] is not None else None
    shares = float(fundamentals_row["diluted_shares"]) if fundamentals_row["diluted_shares"] is not None else None
    revenue = float(fundamentals_row["revenue"]) if fundamentals_row["revenue"] is not None else None

    return {
        "ticker": ticker,
        "price": price,
        "price_as_of": price_row["trade_date"],
        "trailing_pe": trailing_pe(price, eps),
        "trailing_ps": price_to_sales(price, shares, revenue),
        "eps_fiscal_year": fundamentals_row["fiscal_year"],
        "eps_period_end": fundamentals_row["period_end"],
    }
