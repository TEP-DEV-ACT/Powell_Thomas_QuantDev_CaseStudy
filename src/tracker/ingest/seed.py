"""Export/load a gzipped-CSV snapshot of every table, so the dashboard and
Q&A layer can run against stored data with zero network access at review
time (per the PDF's explicit requirement).

    python -m tracker.ingest.seed --export        # dump DB -> data/seed/*.csv.gz
    python -m tracker.ingest.seed --load           # restore data/seed/*.csv.gz -> DB
    python -m tracker.ingest.seed --check-empty    # exit 0 if DB has no data, else 1

`filing_chunks.tsv` is a generated column (STORED, derived from `text`) — it
is excluded from both directions since Postgres recomputes it automatically
and won't accept an explicit value for it on INSERT.
"""
import argparse
import csv
import gzip
import io
import logging
import os
import sys

from tracker.db.session import get_connection
from tracker.logging_config import configure_logging

logger = logging.getLogger(__name__)

csv.field_size_limit(10_000_000)  # filing_sections.text can exceed the 128KB default

SEED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "seed")

# (table, columns) in FK-safe order for LOAD; export just iterates the same list.
TABLES = [
    ("companies", ["ticker", "cik", "name", "fiscal_year_end_month"]),
    ("xbrl_facts", [
        "id", "cik", "ticker", "concept", "unit", "fy", "fp", "form", "accn",
        "period_start", "period_end", "filed", "value",
    ]),
    ("fundamentals", [
        "id", "ticker", "fiscal_year", "period_end", "revenue", "revenue_tag",
        "net_income", "net_income_tag", "eps_diluted", "eps_diluted_tag",
        "diluted_shares", "diluted_shares_tag", "gross_profit", "gross_profit_tag",
        "operating_income", "operating_income_tag", "capex", "capex_tag",
        "operating_cash_flow", "operating_cash_flow_tag",
        "nonoperating_income", "nonoperating_income_tag",
        "income_tax_expense", "income_tax_expense_tag", "source_accn", "filed_at",
    ]),
    ("prices", ["id", "ticker", "trade_date", "open", "high", "low", "close", "volume", "source"]),
    ("filings", ["id", "ticker", "accession_no", "fiscal_year", "filing_date", "period_end", "primary_doc_url"]),
    ("filing_sections", ["id", "filing_id", "item", "char_count", "text"]),
    ("filing_chunks", ["id", "section_id", "chunk_index", "text"]),
    ("macro_series_meta", ["series_id", "title", "units", "source_url"]),
    ("macro_series", ["id", "series_id", "obs_date", "value"]),
    ("ingest_runs", ["id", "source", "started_at", "finished_at", "status", "row_count", "notes"]),
]


def _seed_path(table: str) -> str:
    return os.path.join(SEED_DIR, f"{table}.csv.gz")


def export_all():
    os.makedirs(SEED_DIR, exist_ok=True)
    conn = get_connection()
    try:
        for table, columns in TABLES:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY 1")
                rows = cur.fetchall()
            with gzip.open(_seed_path(table), "wt", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                for row in rows:
                    writer.writerow([row[c] for c in columns])
            logger.info("%s: exported %d rows", table, len(rows))
    finally:
        conn.close()


def _reset_sequence(conn, table: str, columns: list[str]):
    if "id" not in columns:
        return
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', 'id'),
                COALESCE((SELECT MAX(id) FROM {table}), 1),
                true
            )
            """
        )


def load_all():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for table, _columns in reversed(TABLES):
                cur.execute(f"DELETE FROM {table}")
        conn.commit()

        for table, columns in TABLES:
            path = _seed_path(table)
            if not os.path.exists(path):
                logger.info("%s: no seed file, skipping", table)
                continue
            with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
                assert header == columns, f"{table}: seed columns {header} != schema columns {columns}"
                placeholders = ", ".join(["%s"] * len(columns))
                sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
                rows = [[v if v != "" else None for v in row] for row in reader]
            if rows:
                with conn.cursor() as cur:
                    cur.executemany(sql, rows)
            _reset_sequence(conn, table, columns)
            logger.info("%s: loaded %d rows", table, len(rows))
        conn.commit()
    finally:
        conn.close()


def is_empty() -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM companies")
            return cur.fetchone()["n"] == 0
    finally:
        conn.close()


def main():
    configure_logging()
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", action="store_true")
    group.add_argument("--load", action="store_true")
    group.add_argument("--check-empty", action="store_true")
    args = parser.parse_args()

    if args.export:
        export_all()
    elif args.load:
        load_all()
    elif args.check_empty:
        sys.exit(0 if is_empty() else 1)


if __name__ == "__main__":
    main()
