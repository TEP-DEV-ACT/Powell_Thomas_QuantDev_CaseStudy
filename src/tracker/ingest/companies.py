"""Resolve tickers in config.UNIVERSE to CIKs and populate the `companies`
table. Shared by edgar_facts.py and edgar_filings.py so CIK resolution lives
in exactly one place — adding a ticker to config.UNIVERSE is enough.
"""
from tracker.config import UNIVERSE
from tracker.ingest._http import get, sec_session

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def resolve_ciks(session=None) -> dict:
    """Return {ticker: (cik, name)} for every ticker in UNIVERSE."""
    session = session or sec_session()
    data = get(session, TICKERS_URL).json()
    wanted = set(UNIVERSE)
    resolved = {}
    for row in data.values():
        ticker = row["ticker"].upper()
        if ticker in wanted:
            resolved[ticker] = (row["cik_str"], row["title"])
    missing = wanted - resolved.keys()
    if missing:
        raise ValueError(f"Could not resolve CIK for tickers: {missing}")
    return resolved


def fetch_submissions(cik: int, session=None) -> dict:
    session = session or sec_session()
    return get(session, SUBMISSIONS_URL.format(cik=cik)).json()


def upsert_companies(conn, session=None) -> dict:
    """Populate/refresh the companies table. Returns {ticker: (cik, name)}."""
    session = session or sec_session()
    resolved = resolve_ciks(session)
    with conn.cursor() as cur:
        for ticker, (cik, name) in resolved.items():
            submissions = fetch_submissions(cik, session)
            fy_end = submissions.get("fiscalYearEnd")  # "MMDD" or None
            fy_end_month = int(fy_end[:2]) if fy_end else None
            cur.execute(
                """
                INSERT INTO companies (ticker, cik, name, fiscal_year_end_month)
                VALUES (%(ticker)s, %(cik)s, %(name)s, %(fy_end_month)s)
                ON CONFLICT (ticker) DO UPDATE SET
                    cik = EXCLUDED.cik,
                    name = EXCLUDED.name,
                    fiscal_year_end_month = EXCLUDED.fiscal_year_end_month
                """,
                {
                    "ticker": ticker,
                    "cik": cik,
                    "name": name,
                    "fy_end_month": fy_end_month,
                },
            )
    conn.commit()
    return resolved
