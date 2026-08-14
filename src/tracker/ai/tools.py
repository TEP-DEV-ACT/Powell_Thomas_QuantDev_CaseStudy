"""The five tools exposed to the Claude tool-use agent. Each wraps a read-only
metrics/search function, records its call+result into a per-request trace
(surfaced in the UI as the grounding audit trail), and returns JSON text —
never raw numbers computed by the model itself.
"""
import json
import logging
from typing import Optional

from anthropic import beta_tool

from tracker.ai.search import search_filings as _search_filings
from tracker.config import UNIVERSE
from tracker.metrics.capex import get_capex_context as _get_capex_context
from tracker.metrics.queries import compare_companies as _compare_companies
from tracker.metrics.queries import get_fundamentals as _get_fundamentals
from tracker.metrics.valuation import get_valuation as _get_valuation

logger = logging.getLogger(__name__)


def _dump(obj) -> str:
    return json.dumps(obj, default=str)


def build_tools(trace: list) -> list:
    """Returns the 5 @beta_tool-decorated functions, each appending its call
    and result to `trace` as a side effect before answering the model."""

    def record(name: str, tool_input: dict, result) -> None:
        logger.info("AI tool call: %s input=%s", name, tool_input)
        trace.append({"tool": name, "input": tool_input, "result": result})

    def _safe(name: str, tool_input: dict, fn, *args, **kwargs):
        """Run a tool's underlying data fetch, turning any exception (DB
        outage, bad query, etc.) into a structured {"error": ...} result
        instead of letting it propagate and abort the whole chat turn —
        the system prompt already tells the model to say so plainly rather
        than invent an answer when a tool errors (ai/prompts.py rule 3)."""
        try:
            result = fn(*args, **kwargs)
        except Exception:
            logger.exception("AI tool %s failed, input=%s", name, tool_input)
            result = {"error": f"{name} failed due to an internal data error. Tell the user this specific lookup is unavailable right now rather than guessing."}
        record(name, tool_input, result)
        return _dump(result)

    @beta_tool
    def get_fundamentals(ticker: str, years: int = 5) -> str:
        """Reported and derived annual fundamentals for one company: revenue,
        net income, diluted EPS, gross margin, operating margin, net income
        margin, free cash flow, FCF margin, the per-share variants of
        revenue/net income/free cash flow, and each one's year-over-year
        change. Also includes other_income_adjustments (the pre-tax
        non-operating income/expense embedded in net income — the as-reported
        "other income (expense), net" line, which may also bundle in interest
        income/expense for filers that don't tag it separately),
        effective_tax_rate (income_tax_expense / pretax income for the year),
        adjusted_net_income (net income with that adjustment backed out at
        the company's own effective tax rate, so an after-tax investment-marks
        swing doesn't read as a change in operating performance), and
        adjusted_net_income_margin. All are null for a fiscal year when no
        source tag matched or the tax rate can't be derived — a real gap,
        not a zero.
        Absolute dollar figures are in whole US dollars as reported to EDGAR,
        not millions. Use this for questions about a single company's
        reported numbers or growth over time.

        Args:
            ticker: Stock ticker — one of NVDA, MSFT, AAPL, GOOGL, ETN.
            years: How many of the most recent fiscal years to return.
        """
        ticker = ticker.upper()
        tool_input = {"ticker": ticker, "years": years}
        if ticker not in UNIVERSE:
            result = {"error": f"unknown ticker {ticker}, must be one of {UNIVERSE}"}
            record("get_fundamentals", tool_input, result)
            return _dump(result)
        return _safe("get_fundamentals", tool_input, _get_fundamentals, ticker, years=years)

    @beta_tool
    def compare_companies(metric: str, fiscal_year: int) -> str:
        """Rank all 5 tracked companies on one reported/derived metric for a
        single fiscal year, highest to lowest. Use this for "which company
        had the highest/lowest X" or any cross-company comparison.

        Prefer the margin/yield metrics for cross-company questions — the
        absolute dollar metrics mostly just rank the companies by size.
        fcf_yield divides that fiscal year's free cash flow by *today's*
        market cap (latest close x latest reported diluted shares), so it
        answers "what would a buyer at today's price be getting on that
        year's cash flow," not a point-in-time historical yield — say so if
        the question implies the latter. The per-share metrics divide by the
        as-reported diluted share count, which EDGAR does not restate for
        stock splits, so a company's per-share series steps sharply across
        its split years (GOOGL 20:1 in 2022, NVDA 10:1 in FY2025, AAPL 4:1 in
        2020) — margins and yields are immune to this and should be preferred
        when available.

        Args:
            metric: One of revenue, net_income, free_cash_flow, eps_diluted,
                revenue_per_share, net_income_per_share, fcf_per_share,
                gross_margin, operating_margin, net_income_margin,
                fcf_margin, fcf_yield.
            fiscal_year: The fiscal year to compare, e.g. 2024.
        """
        tool_input = {"metric": metric, "fiscal_year": fiscal_year}
        return _safe("compare_companies", tool_input, _compare_companies, metric, fiscal_year)

    @beta_tool
    def get_valuation(ticker: str) -> str:
        """Trailing P/E, trailing P/S, market cap, and FCF yield for one
        company: the latest market close joined against the most recently
        reported annual diluted EPS, revenue, and free cash flow. All ratios
        are explicitly trailing; as-of dates for the price and the
        EPS/revenue/FCF are included so staleness is visible. Use this for
        any valuation/multiple question — never estimate a multiple from
        memory.

        Args:
            ticker: Stock ticker — one of NVDA, MSFT, AAPL, GOOGL, ETN.
        """
        ticker = ticker.upper()
        tool_input = {"ticker": ticker}
        if ticker not in UNIVERSE:
            result = {"error": f"unknown ticker {ticker}, must be one of {UNIVERSE}"}
            record("get_valuation", tool_input, result)
            return _dump(result)

        def _fetch():
            return _get_valuation(ticker) or {"error": f"no valuation data for {ticker}"}

        return _safe("get_valuation", tool_input, _fetch)

    @beta_tool
    def get_capex_context(ticker: str) -> str:
        """A company's capex intensity (capex / revenue) by fiscal year,
        alongside the national capex cycle (FRED Private Nonresidential
        Fixed Investment) and a capex-cycle beta (company capex YoY growth
        divided by national capex YoY growth). Use this for questions about
        capital spending, the AI/data-center capex cycle, or how a company's
        investment pace compares to the broader economy.

        Args:
            ticker: Stock ticker — one of NVDA, MSFT, AAPL, GOOGL, ETN.
        """
        ticker = ticker.upper()
        tool_input = {"ticker": ticker}
        if ticker not in UNIVERSE:
            result = {"error": f"unknown ticker {ticker}, must be one of {UNIVERSE}"}
            record("get_capex_context", tool_input, result)
            return _dump(result)
        return _safe("get_capex_context", tool_input, _get_capex_context, ticker)

    @beta_tool
    def search_filings(
        query: str,
        ticker: Optional[str] = None,
        item: Optional[str] = None,
        fiscal_year: Optional[int] = None,
    ) -> str:
        """Full-text search over each company's 10-K Item 1A (Risk Factors)
        and Item 7 (MD&A) narrative for its two most recent fiscal years.
        Use this for any question about what management said, stated risk
        factors, or narrative explanations behind a number — never for
        numeric facts, which come from the other tools. Returns ranked text
        excerpts with ticker/fiscal_year/item/accession citations. The
        dataset is trailing-only: it contains no forward guidance, estimates,
        or price targets, so decline questions asking for those rather than
        inferring an answer.

        Args:
            query: Free-text search query.
            ticker: Optional ticker filter — one of NVDA, MSFT, AAPL, GOOGL, ETN.
            item: Optional filing item filter — '1A' (Risk Factors) or '7' (MD&A).
            fiscal_year: Optional fiscal year filter.
        """
        ticker = ticker.upper() if ticker else None
        tool_input = {"query": query, "ticker": ticker, "item": item, "fiscal_year": fiscal_year}
        return _safe(
            "search_filings", tool_input, _search_filings,
            query, ticker=ticker, item=item, fiscal_year=fiscal_year,
        )

    return [get_fundamentals, compare_companies, get_valuation, get_capex_context, search_filings]
