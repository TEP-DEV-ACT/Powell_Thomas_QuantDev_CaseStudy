"""Ingest raw EDGAR XBRL company facts into xbrl_facts.

Landing table only — no tag selection here. We store every us-gaap concept
reported on an annual 10-K (form='10-K', fp='FY') so restatements and
alternate tags stay queryable; transform/normalize.py picks winners later.

A 10-K can report a *duration* concept (revenue, net income, ...) twice under
the same tag with fy/fp/form/accn all identical: once for the real annual
period, and again for a sub-period disclosed elsewhere in the same filing
(e.g. Apple tags its Q4-only "selected quarterly data" footnote with the same
RevenueFromContractWithCustomerExcludingAssessedTax concept as the full-year
figure). Since xbrl_facts is keyed on (cik, concept, unit, fy, fp, form,
accn) — not on the fact's own period dates — these collide, and whichever one
happened to be inserted last would silently win. Any duration fact under
~300 days is therefore rejected outright: this tracker is annual-only by
design (see PLAN.md's deliberate cuts), so it's never the fact we want, and
dropping it up front avoids the collision as well as the wrong number.

Run: python -m tracker.ingest.edgar_facts
"""
import logging
from datetime import date

from tracker.db.session import get_connection
from tracker.ingest._http import get, sec_session
from tracker.ingest._runlog import track_run
from tracker.ingest.companies import upsert_companies
from tracker.logging_config import configure_logging

logger = logging.getLogger(__name__)

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
MIN_ANNUAL_DURATION_DAYS = 300


def _iter_annual_facts(company_facts: dict):
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for concept, payload in us_gaap.items():
        for unit, entries in payload.get("units", {}).items():
            for entry in entries:
                if entry.get("form") != "10-K" or entry.get("fp") != "FY":
                    continue
                start, end = entry.get("start"), entry.get("end")
                if start and end:
                    duration_days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                    if duration_days < MIN_ANNUAL_DURATION_DAYS:
                        continue
                yield concept, unit, entry


def ingest_facts_for_ticker(conn, ticker: str, cik: int, session) -> int:
    company_facts = get(session, FACTS_URL.format(cik=cik)).json()
    rows = list(_iter_annual_facts(company_facts))
    with conn.cursor() as cur:
        for concept, unit, entry in rows:
            cur.execute(
                """
                INSERT INTO xbrl_facts
                    (cik, ticker, concept, unit, fy, fp, form, accn,
                     period_start, period_end, filed, value)
                VALUES
                    (%(cik)s, %(ticker)s, %(concept)s, %(unit)s, %(fy)s, %(fp)s,
                     %(form)s, %(accn)s, %(period_start)s, %(period_end)s,
                     %(filed)s, %(value)s)
                ON CONFLICT (cik, concept, unit, fy, fp, form, accn) DO UPDATE SET
                    value = EXCLUDED.value,
                    filed = EXCLUDED.filed,
                    period_start = EXCLUDED.period_start,
                    period_end = EXCLUDED.period_end
                """,
                {
                    "cik": cik,
                    "ticker": ticker,
                    "concept": concept,
                    "unit": unit,
                    "fy": entry["fy"],
                    "fp": entry["fp"],
                    "form": entry["form"],
                    "accn": entry["accn"],
                    "period_start": entry.get("start"),
                    "period_end": entry.get("end"),
                    "filed": entry["filed"],
                    "value": entry["val"],
                },
            )
    conn.commit()
    return len(rows)


def run():
    session = sec_session()
    conn = get_connection()
    try:
        resolved = upsert_companies(conn, session)
        with track_run(conn, "edgar_facts") as state:
            total = 0
            for ticker, (cik, _name) in resolved.items():
                n = ingest_facts_for_ticker(conn, ticker, cik, session)
                logger.info("%s (CIK %d): %d annual fact rows", ticker, cik, n)
                total += n
            state["row_count"] = total
    finally:
        conn.close()


if __name__ == "__main__":
    configure_logging()
    run()
