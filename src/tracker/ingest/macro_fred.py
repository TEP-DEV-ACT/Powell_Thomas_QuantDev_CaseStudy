"""Ingest FRED macro capex series into macro_series (+ macro_series_meta).

Uses the keyless fredgraph.csv endpoint by default so ingestion never
hard-blocks on a key graders don't have; if FRED_API_KEY is set, series
metadata (title/units) is enriched via the JSON API.

Run: python -m tracker.ingest.macro_fred
"""
import io
import logging

import pandas as pd
import requests

from tracker.config import FRED_API_KEY, FRED_SERIES
from tracker.db.session import get_connection
from tracker.ingest._runlog import track_run
from tracker.logging_config import configure_logging

logger = logging.getLogger(__name__)

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
SERIES_META_URL = "https://api.stlouisfed.org/fred/series"

_FALLBACK_META = {
    "PNFI": {
        "title": "Private Nonresidential Fixed Investment",
        "units": "Billions of Dollars, SAAR",
    },
    "Y033RC1Q027SBEA": {
        "title": "Private Fixed Investment: Information Processing Equipment",
        "units": "Billions of Dollars, SAAR",
    },
}


def _fetch_series(series_id: str) -> pd.DataFrame:
    resp = requests.get(CSV_URL.format(series_id=series_id), timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = ["obs_date", "value"]
    df["obs_date"] = pd.to_datetime(df["obs_date"]).dt.date
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["value"])


def _fetch_meta(series_id: str) -> dict:
    if not FRED_API_KEY:
        return {**_FALLBACK_META.get(series_id, {}), "source_url": f"https://fred.stlouisfed.org/series/{series_id}"}
    resp = requests.get(
        SERIES_META_URL,
        params={"series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    series = resp.json()["seriess"][0]
    return {
        "title": series["title"],
        "units": series["units"],
        "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
    }


def ingest_series(conn, series_id: str) -> int:
    df = _fetch_series(series_id)
    meta = _fetch_meta(series_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO macro_series_meta (series_id, title, units, source_url)
            VALUES (%(series_id)s, %(title)s, %(units)s, %(source_url)s)
            ON CONFLICT (series_id) DO UPDATE SET
                title = EXCLUDED.title, units = EXCLUDED.units, source_url = EXCLUDED.source_url
            """,
            {"series_id": series_id, **meta},
        )
        for row in df.itertuples(index=False):
            cur.execute(
                """
                INSERT INTO macro_series (series_id, obs_date, value)
                VALUES (%(series_id)s, %(obs_date)s, %(value)s)
                ON CONFLICT (series_id, obs_date) DO UPDATE SET value = EXCLUDED.value
                """,
                {"series_id": series_id, "obs_date": row.obs_date, "value": float(row.value)},
            )
    conn.commit()
    return len(df)


def run():
    conn = get_connection()
    try:
        with track_run(conn, "macro_fred") as state:
            total = 0
            for series_id in FRED_SERIES.values():
                n = ingest_series(conn, series_id)
                logger.info("%s: %d observations", series_id, n)
                total += n
            state["row_count"] = total
            if not FRED_API_KEY:
                logger.warning("no FRED_API_KEY set; used keyless CSV endpoint + hardcoded fallback metadata")
                state["notes"] = "no FRED_API_KEY set; used keyless CSV endpoint + hardcoded fallback metadata"
    finally:
        conn.close()


if __name__ == "__main__":
    configure_logging()
    run()
