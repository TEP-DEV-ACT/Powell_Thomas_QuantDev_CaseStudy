"""JSON API — direct reads over the metrics layer. No ingestion is ever
triggered from a web request; the dashboard runs entirely off stored data.
"""
import csv
import functools
import io
import logging

from flask import Blueprint, Response, jsonify, request

from tracker.ai.agent import ask as ask_agent
from tracker.config import UNIVERSE
from tracker.db.session import get_connection
from tracker.metrics.capex import get_capex_context
from tracker.metrics.queries import compare_companies, get_fundamentals
from tracker.metrics.valuation import get_valuation

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__, url_prefix="/api")

# The chat transcript round-trips through the browser, so it is untrusted input
# and it is also what the next request has to pay for in tokens. Both limits are
# enforced server-side; the system prompt is never client-influenced.
MAX_HISTORY_TURNS = 10
MAX_HISTORY_CHARS = 4000


def _json_errors(view):
    """Turn an unhandled exception in a route (DB outage, bad query, a
    metrics function raising on unexpected data) into a clean 500 JSON body
    instead of Flask's default HTML error page or a leaked stack trace —
    every route in this module is a JSON API, so its failures should be too.
    Routes that need a more specific status/message (e.g. /ask's 502 for an
    agent error, the 404s for an unknown ticker) still handle those cases
    explicitly before this ever triggers."""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except Exception:
            logger.exception("%s failed", view.__name__)
            return jsonify({"error": "internal server error"}), 500
    return wrapper


def _clean_history(raw) -> list[dict]:
    """Validate and bound a client-supplied transcript.

    Raises ValueError on anything malformed rather than silently dropping it —
    a client that posts a broken transcript has a bug worth surfacing.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("history must be a list")

    turns: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("each history entry must be an object")
        role, content = entry.get("role"), entry.get("content")
        if role not in ("user", "assistant"):
            raise ValueError(f"invalid history role: {role!r}")
        if not isinstance(content, str):
            raise ValueError("history content must be a string")
        content = content.strip()[:MAX_HISTORY_CHARS]
        if not content:
            continue
        # The API wants alternating turns; a client that appends two user
        # messages in a row (e.g. after a failed request) gets them merged
        # rather than a 400 from Anthropic.
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] = f"{turns[-1]['content']}\n\n{content}"
        else:
            turns.append({"role": role, "content": content})

    turns = turns[-MAX_HISTORY_TURNS:]
    # The new question is appended as a user turn, so a transcript ending in an
    # unanswered user message would produce two user turns in a row.
    if turns and turns[0]["role"] == "assistant":
        turns = turns[1:]
    if turns and turns[-1]["role"] == "user":
        turns = turns[:-1]
    return turns


@api.get("/companies")
@_json_errors
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
@_json_errors
def fundamentals(ticker: str):
    ticker = ticker.upper()
    years = request.args.get("years", type=int)
    logger.info("GET /api/fundamentals/%s years=%s", ticker, years)
    if ticker not in UNIVERSE:
        logger.warning("fundamentals: unknown ticker %s", ticker)
        return jsonify({"error": f"unknown ticker: {ticker}"}), 404
    return jsonify(get_fundamentals(ticker, years=years))


@api.get("/compare")
@_json_errors
def compare():
    metric = request.args.get("metric")
    fiscal_year = request.args.get("fiscal_year", type=int)
    logger.info("GET /api/compare metric=%s fiscal_year=%s", metric, fiscal_year)
    if not metric or fiscal_year is None:
        return jsonify({"error": "metric and fiscal_year are required"}), 400
    return jsonify(compare_companies(metric, fiscal_year))


@api.get("/valuation/<ticker>")
@_json_errors
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
@_json_errors
def capex(ticker: str):
    ticker = ticker.upper()
    logger.info("GET /api/capex/%s", ticker)
    if ticker not in UNIVERSE:
        logger.warning("capex: unknown ticker %s", ticker)
        return jsonify({"error": f"unknown ticker: {ticker}"}), 404
    return jsonify(get_capex_context(ticker))


@api.get("/prices/<ticker>")
@_json_errors
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


@api.get("/prices/<ticker>.csv")
@_json_errors
def prices_csv(ticker: str):
    ticker = ticker.upper()
    days = request.args.get("days", default=365, type=int)
    logger.info("GET /api/prices/%s.csv days=%d", ticker, days)
    if ticker not in UNIVERSE:
        logger.warning("prices_csv: unknown ticker %s", ticker)
        return jsonify({"error": f"unknown ticker: {ticker}"}), 404
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, open, high, low, close, volume FROM prices
                WHERE ticker = %(ticker)s
                ORDER BY trade_date DESC LIMIT %(days)s
                """,
                {"ticker": ticker, "days": days},
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    rows.reverse()

    fieldnames = ["trade_date", "open", "high", "low", "close", "volume"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{ticker}_price.csv"'},
    )


@api.post("/ask")
def ask():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    logger.info("POST /api/ask question=%r", question)
    if not question:
        return jsonify({"error": "question is required"}), 400
    try:
        history = _clean_history(payload.get("history"))
    except ValueError as exc:
        logger.warning("POST /api/ask rejected history: %s", exc)
        return jsonify({"error": str(exc)}), 400
    try:
        result = ask_agent(question, history=history)
    except Exception as exc:
        logger.exception("AI agent error answering question=%r", question)
        return jsonify({"error": f"agent error: {exc}"}), 502
    return jsonify(result)


@api.get("/filings/<ticker>")
@_json_errors
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
