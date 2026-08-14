"""JSON API — direct reads over the metrics layer. No ingestion is ever
triggered from a web request; the dashboard runs entirely off stored data.
"""
import logging

from flask import Blueprint, jsonify, request

from tracker.ai.agent import ask as ask_agent
from tracker.config import UNIVERSE
from tracker.db.session import get_connection
from tracker.metrics.capex import get_capex_context
from tracker.metrics.queries import compare_companies, get_fundamentals
from tracker.metrics.valuation import get_valuation

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")


@api.get("/companies")
def companies():
    logger.info("GET /api/companies")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, cik, name, fiscal_year_end_month FROM companies")
            by_ticker = {row["ticker"]: row for row in cur.fetchall()}
    finally:
        conn.close()
    return jsonify([by_ticker[t] for t in UNIVERSE if t in by_ticker])


@api.get("/fundamentals/<ticker>")
def fundamentals(ticker: str):
    ticker = ticker.upper()
    years = request.args.get("years", type=int)
    logger.info("GET /api/fundamentals/%s years=%s", ticker, years)
    if ticker not in UNIVERSE:
        logger.warning("fundamentals: unknown ticker %s", ticker)
        return jsonify({"error": f"unknown ticker: {ticker}"}), 404
    return jsonify(get_fundamentals(ticker, years=years))


@api.get("/compare")
def compare():
    metric = request.args.get("metric")
    fiscal_year = request.args.get("fiscal_year", type=int)
    logger.info("GET /api/compare metric=%s fiscal_year=%s", metric, fiscal_year)
    if not metric or fiscal_year is None:
        return jsonify({"error": "metric and fiscal_year are required"}), 400
    return jsonify(compare_companies(metric, fiscal_year))


@api.get("/valuation/<ticker>")
def valuation(ticker: str):
    ticker = ticker.upper()
    logger.info("GET /api/valuation/%s", ticker)
    if ticker not in UNIVERSE:
        logger.warning("valuation: unknown ticker %s", ticker)
        return jsonify({"error": f"unknown ticker: {ticker}"}), 404
    result = get_valuation(ticker)
    if result is None:
        logger.warning("valuation: no price/fundamentals data for %s", ticker)
        return jsonify({"error": f"no price/fundamentals data for {ticker}"}), 404
    return jsonify(result)


@api.get("/capex/<ticker>")
def capex(ticker: str):
    ticker = ticker.upper()
    logger.info("GET /api/capex/%s", ticker)
    if ticker not in UNIVERSE:
        logger.warning("capex: unknown ticker %s", ticker)
        return jsonify({"error": f"unknown ticker: {ticker}"}), 404
    return jsonify(get_capex_context(ticker))


@api.get("/prices/<ticker>")
def prices(ticker: str):
    ticker = ticker.upper()
    days = request.args.get("days", default=365, type=int)
    logger.info("GET /api/prices/%s days=%d", ticker, days)
    if ticker not in UNIVERSE:
        logger.warning("prices: unknown ticker %s", ticker)
        return jsonify({"error": f"unknown ticker: {ticker}"}), 404
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, close FROM prices
                WHERE ticker = %(ticker)s
                ORDER BY trade_date DESC LIMIT %(days)s
                """,
                {"ticker": ticker, "days": days},
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    rows.reverse()
    return jsonify(rows)


@api.post("/ask")
def ask():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    logger.info("POST /api/ask question=%r", question)
    if not question:
        return jsonify({"error": "question is required"}), 400
    try:
        result = ask_agent(question)
    except Exception as exc:
        logger.exception("AI agent error answering question=%r", question)
        return jsonify({"error": f"agent error: {exc}"}), 502
    return jsonify(result)


@api.get("/filings/<ticker>")
def filings(ticker: str):
    ticker = ticker.upper()
    logger.info("GET /api/filings/%s", ticker)
    if ticker not in UNIVERSE:
        logger.warning("filings: unknown ticker %s", ticker)
        return jsonify({"error": f"unknown ticker: {ticker}"}), 404
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, accession_no, fiscal_year, filing_date, period_end, primary_doc_url
                FROM filings WHERE ticker = %(ticker)s ORDER BY fiscal_year DESC
                """,
                {"ticker": ticker},
            )
            return jsonify(cur.fetchall())
    finally:
        conn.close()
