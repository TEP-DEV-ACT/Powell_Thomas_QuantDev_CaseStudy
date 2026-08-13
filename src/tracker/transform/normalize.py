"""Normalize xbrl_facts into one row per (ticker, fiscal_year) in fundamentals.

For each logical concept, walk transform.concepts.CONCEPT_CHAINS in order and
take the first tag that has a value for that (cik, fy); if EDGAR shows the
same tag from multiple filings (restatement), the latest-filed one wins. The
winning tag is recorded next to the value.

Tag resolution (resolve_concept_for_fy / normalize_facts) is pure Python over
an in-memory list of fact dicts, so it's unit-testable without a database —
see tests/test_concepts.py. This module's DB-touching code just fetches that
list once per company and upserts the result.

Run: python -m tracker.transform.normalize
"""
from tracker.db.session import get_connection
from tracker.transform.concepts import CONCEPT_CHAINS, FUNDAMENTALS_COLUMNS

UNIT_BY_CONCEPT = {
    "revenue": "USD",
    "net_income": "USD",
    "gross_profit": "USD",
    "cost_of_revenue": "USD",
    "operating_income": "USD",
    "capex": "USD",
    "operating_cash_flow": "USD",
    "eps_diluted": "USD/shares",
    "diluted_shares": "shares",
}

# Priority order for which resolved concept supplies period_end/accn/filed_at
# metadata on the fundamentals row (they should agree across concepts for the
# same fiscal year; this just picks a deterministic source).
METADATA_PRIORITY = [
    "revenue",
    "net_income",
    "operating_cash_flow",
    "gross_profit",
    "operating_income",
    "capex",
    "eps_diluted",
    "diluted_shares",
]


def resolve_concept_for_fy(facts: list[dict], logical_concept: str, fy: int) -> tuple[str | None, dict | None]:
    """Walk the tag chain for `logical_concept`; return (winning_tag, fact)
    for the first tag with a matching (fy, unit) fact, latest-filed wins."""
    unit = UNIT_BY_CONCEPT[logical_concept]
    for tag in CONCEPT_CHAINS[logical_concept]:
        matches = [f for f in facts if f["concept"] == tag and f["unit"] == unit and f["fy"] == fy]
        if matches:
            best = max(matches, key=lambda f: f["filed"])
            return tag, best
    return None, None


def normalize_facts(facts: list[dict]) -> list[dict]:
    """Pure transform: xbrl_facts-shaped dicts for one company -> one
    fundamentals-shaped dict per fiscal year present in `facts`."""
    fiscal_years = sorted({f["fy"] for f in facts})
    rows = []
    for fy in fiscal_years:
        resolved = {
            logical_concept: resolve_concept_for_fy(facts, logical_concept, fy)
            for logical_concept in CONCEPT_CHAINS
        }
        if all(fact is None for _tag, fact in resolved.values()):
            continue

        metadata_fact = None
        for logical_concept in METADATA_PRIORITY:
            _tag, fact = resolved[logical_concept]
            if fact is not None:
                metadata_fact = fact
                break

        row = {
            "fiscal_year": fy,
            "period_end": metadata_fact["period_end"] if metadata_fact else None,
            "source_accn": metadata_fact["accn"] if metadata_fact else None,
            "filed_at": metadata_fact["filed"] if metadata_fact else None,
        }
        for logical_concept, (tag, fact) in resolved.items():
            if logical_concept not in FUNDAMENTALS_COLUMNS:
                continue  # helper concept only (e.g. cost_of_revenue), not its own column
            value_col, tag_col = FUNDAMENTALS_COLUMNS[logical_concept]
            row[value_col] = fact["value"] if fact else None
            row[tag_col] = tag if fact else None

        # Some filers (GOOGL, ETN) never present a GrossProfit subtotal line
        # at all; derive it from revenue - cost_of_revenue when possible.
        if row["gross_profit"] is None:
            _revenue_tag, revenue_fact = resolved["revenue"]
            _cost_tag, cost_fact = resolved["cost_of_revenue"]
            if revenue_fact is not None and cost_fact is not None:
                row["gross_profit"] = revenue_fact["value"] - cost_fact["value"]
                row["gross_profit_tag"] = f"derived:revenue-{_cost_tag}"

        rows.append(row)
    return rows


def _fetch_facts(conn, cik: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT concept, unit, fy, filed, accn, period_end, value
            FROM xbrl_facts WHERE cik = %(cik)s
            """,
            {"cik": cik},
        )
        return cur.fetchall()


def _upsert_fundamentals_row(conn, ticker: str, row: dict) -> None:
    params = {"ticker": ticker, **row}
    columns = ", ".join(params.keys())
    placeholders = ", ".join(f"%({k})s" for k in params)
    update_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in params if k not in ("ticker", "fiscal_year"))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO fundamentals ({columns})
            VALUES ({placeholders})
            ON CONFLICT (ticker, fiscal_year) DO UPDATE SET {update_clause}
            """,
            params,
        )


def normalize_company(conn, ticker: str, cik: int) -> int:
    facts = _fetch_facts(conn, cik)
    rows = normalize_facts(facts)
    for row in rows:
        _upsert_fundamentals_row(conn, ticker, row)
    conn.commit()
    return len(rows)


def run():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, cik FROM companies ORDER BY ticker")
            companies = cur.fetchall()
        for company in companies:
            n = normalize_company(conn, company["ticker"], company["cik"])
            print(f"{company['ticker']}: {n} fiscal-year rows normalized")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
