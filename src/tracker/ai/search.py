"""Lexical full-text search over 10-K Item 1A/7 chunks (Postgres FTS —
see PLAN.md's rationale: no embedding-provider dependency, exact citations).
"""
from tracker.db.session import get_connection

SEARCH_SQL = """
SELECT
    f.ticker, fs.item, f.fiscal_year, f.accession_no, f.primary_doc_url,
    ts_headline('english', fc.text, websearch_to_tsquery('english', %(query)s),
                'MaxFragments=1, MaxWords=60, MinWords=20') AS snippet,
    ts_rank(fc.tsv, websearch_to_tsquery('english', %(query)s)) AS rank
FROM filing_chunks fc
JOIN filing_sections fs ON fs.id = fc.section_id
JOIN filings f ON f.id = fs.filing_id
WHERE fc.tsv @@ websearch_to_tsquery('english', %(query)s)
  AND (%(ticker)s::text IS NULL OR f.ticker = %(ticker)s::text)
  AND (%(item)s::text IS NULL OR fs.item = %(item)s::text)
  AND (%(fiscal_year)s::int IS NULL OR f.fiscal_year = %(fiscal_year)s::int)
ORDER BY rank DESC
LIMIT 8
"""


def search_filings(
    query: str,
    ticker: str | None = None,
    item: str | None = None,
    fiscal_year: int | None = None,
    conn=None,
) -> list[dict]:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                SEARCH_SQL,
                {"query": query, "ticker": ticker, "item": item, "fiscal_year": fiscal_year},
            )
            return cur.fetchall()
    finally:
        if owns_conn:
            conn.close()
