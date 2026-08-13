"""Ingest ~3 years of daily OHLCV per ticker into `prices`.

Primary source: yfinance. Yahoo periodically rate-limits or throttles by IP;
if yfinance raises or returns an empty frame, fall back to Stooq's CSV
endpoint. Which source served each ticker is recorded in ingest_runs.notes.

Run: python -m tracker.ingest.prices
"""
import io

import pandas as pd
import requests
import yfinance as yf

from tracker.config import UNIVERSE
from tracker.db.session import get_connection
from tracker.ingest._runlog import track_run

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}.us&i=d"
PERIOD = "3y"


def _from_yfinance(ticker: str) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=PERIOD, auto_adjust=False)
    if df.empty:
        raise ValueError("yfinance returned no rows")
    df = df.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
    df.columns = ["trade_date", "open", "high", "low", "close", "volume"]
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


def _from_stooq(ticker: str) -> pd.DataFrame:
    resp = requests.get(STOOQ_URL.format(symbol=ticker.lower()), timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    if df.empty or "Date" not in df.columns:
        raise ValueError("stooq returned no usable rows")
    df = df.rename(
        columns={
            "Date": "trade_date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df[["trade_date", "open", "high", "low", "close", "volume"]]


def _fetch_prices(ticker: str) -> tuple[pd.DataFrame, str]:
    try:
        return _from_yfinance(ticker), "yfinance"
    except Exception as exc:
        print(f"{ticker}: yfinance failed ({exc}), falling back to stooq")
        return _from_stooq(ticker), "stooq"


def ingest_prices_for_ticker(conn, ticker: str) -> tuple[int, str]:
    df, source = _fetch_prices(ticker)
    with conn.cursor() as cur:
        for row in df.itertuples(index=False):
            cur.execute(
                """
                INSERT INTO prices (ticker, trade_date, open, high, low, close, volume, source)
                VALUES (%(ticker)s, %(trade_date)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(source)s)
                ON CONFLICT (ticker, trade_date) DO UPDATE SET
                    open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                    close = EXCLUDED.close, volume = EXCLUDED.volume, source = EXCLUDED.source
                """,
                {
                    "ticker": ticker,
                    "trade_date": row.trade_date,
                    "open": None if pd.isna(row.open) else float(row.open),
                    "high": None if pd.isna(row.high) else float(row.high),
                    "low": None if pd.isna(row.low) else float(row.low),
                    "close": float(row.close),
                    "volume": None if pd.isna(row.volume) else int(row.volume),
                    "source": source,
                },
            )
    conn.commit()
    return len(df), source


def run():
    conn = get_connection()
    try:
        with track_run(conn, "prices") as state:
            total = 0
            fallback_used = []
            for ticker in UNIVERSE:
                n, source = ingest_prices_for_ticker(conn, ticker)
                print(f"{ticker}: {n} rows via {source}")
                total += n
                if source != "yfinance":
                    fallback_used.append(f"{ticker}:{source}")
            state["row_count"] = total
            if fallback_used:
                state["notes"] = "fallback used: " + ", ".join(fallback_used)
    finally:
        conn.close()


if __name__ == "__main__":
    run()
