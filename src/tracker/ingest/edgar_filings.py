"""Ingest 10-K filing metadata (latest two per ticker) into `filings`, then
fetch each primary document's HTML for section extraction.

Run: python -m tracker.ingest.edgar_filings
"""
from tracker.db.session import get_connection
from tracker.ingest._http import get, sec_session
from tracker.ingest._runlog import track_run
from tracker.ingest.companies import fetch_submissions, upsert_companies

ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodashes}/{primary_doc}"
LATEST_N_FILINGS = 2


def list_latest_10ks(cik: int, session) -> list[dict]:
    submissions = fetch_submissions(cik, session)
    recent = submissions["filings"]["recent"]
    rows = []
    for i, form in enumerate(recent["form"]):
        if form != "10-K":
            continue
        accn = recent["accessionNumber"][i]
        rows.append(
            {
                "accession_no": accn,
                "filing_date": recent["filingDate"][i],
                "period_end": recent["reportDate"][i],
                "primary_doc": recent["primaryDocument"][i],
                "primary_doc_url": ARCHIVES_URL.format(
                    cik=cik,
                    accn_nodashes=accn.replace("-", ""),
                    primary_doc=recent["primaryDocument"][i],
                ),
                "fiscal_year": int(recent["reportDate"][i][:4]),
            }
        )
    rows.sort(key=lambda r: r["filing_date"], reverse=True)
    return rows[:LATEST_N_FILINGS]


def upsert_filing(conn, ticker: str, filing: dict) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filings (ticker, accession_no, fiscal_year, filing_date, period_end, primary_doc_url)
            VALUES (%(ticker)s, %(accession_no)s, %(fiscal_year)s, %(filing_date)s, %(period_end)s, %(primary_doc_url)s)
            ON CONFLICT (ticker, accession_no) DO UPDATE SET
                fiscal_year = EXCLUDED.fiscal_year,
                filing_date = EXCLUDED.filing_date,
                period_end = EXCLUDED.period_end,
                primary_doc_url = EXCLUDED.primary_doc_url
            RETURNING id
            """,
            {"ticker": ticker, **filing},
        )
        filing_id = cur.fetchone()["id"]
    conn.commit()
    return filing_id


def fetch_filing_html(filing: dict, session) -> str:
    return get(session, filing["primary_doc_url"]).text


def run():
    from tracker.transform.sections import extract_and_store_sections

    session = sec_session()
    conn = get_connection()
    try:
        resolved = upsert_companies(conn, session)
        with track_run(conn, "edgar_filings") as state:
            total = 0
            for ticker, (cik, _name) in resolved.items():
                filings = list_latest_10ks(cik, session)
                for filing in filings:
                    filing_id = upsert_filing(conn, ticker, filing)
                    html = fetch_filing_html(filing, session)
                    counts = extract_and_store_sections(conn, filing_id, html)
                    print(f"{ticker} FY{filing['fiscal_year']} ({filing['accession_no']}): {counts}")
                    total += 1
            state["row_count"] = total
    finally:
        conn.close()


if __name__ == "__main__":
    run()
