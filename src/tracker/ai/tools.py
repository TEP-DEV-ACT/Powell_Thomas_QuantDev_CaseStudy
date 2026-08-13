"""The five tools exposed to the Claude tool-use agent. Each wraps a read-only
metrics/search function, records its call+result into a per-request trace
(surfaced in the UI as the grounding audit trail), and returns JSON text —
never raw numbers computed by the model itself.
"""
import json
from typing import Optional

from anthropic import beta_tool

from tracker.ai.search import search_filings as _search_filings
from tracker.config import UNIVERSE
from tracker.metrics.capex import get_capex_context as _get_capex_context
from tracker.metrics.queries import compare_companies as _compare_companies
from tracker.metrics.queries import get_fundamentals as _get_fundamentals
from tracker.metrics.valuation import get_valuation as _get_valuation


def _dump(obj) -> str:
    return json.dumps(obj, default=str)


def build_tools(trace: list) -> list:
    """Returns the 5 @beta_tool-decorated functions, each appending its call
    and result to `trace` as a side effect before answering the model."""

    def record(name: str, tool_input: dict, result) -> None:
        trace.append({"tool": name, "input": tool_input, "result": result})

    @beta_tool
    def get_fundamentals(ticker: str, years: int = 5) -> str:
        """Reported and derived annual fundamentals for one company: revenue,
        net income, diluted EPS, gross margin, operating margin, free cash
        flow, and each one's year-over-year change. Use this for questions
        about a single company's reported numbers or growth over time.

        Args:
            ticker: Stock ticker — one of NVDA, MSFT, AAPL, GOOGL, ETN.
            years: How many of the most recent fiscal years to return.
        """
        ticker = ticker.upper()
        result = (
            {"error": f"unknown ticker {ticker}, must be one of {UNIVERSE}"}
            if ticker not in UNIVERSE
            else _get_fundamentals(ticker, years=years)
        )
        record("get_fundamentals", {"ticker": ticker, "years": years}, result)
        return _dump(result)

    @beta_tool
    def compare_companies(metric: str, fiscal_year: int) -> str:
        """Rank all 5 tracked companies on one reported/derived metric for a
        single fiscal year, highest to lowest. Use this for "which company
        had the highest/lowest X" or any cross-company comparison.

        Args:
            metric: One of revenue, net_income, eps_diluted, gross_margin, operating_margin, free_cash_flow.
            fiscal_year: The fiscal year to compare, e.g. 2024.
        """
        result = _compare_companies(metric, fiscal_year)
        record("compare_companies", {"metric": metric, "fiscal_year": fiscal_year}, result)
        return _dump(result)

    @beta_tool
    def get_valuation(ticker: str) -> str:
        """Trailing P/E and trailing P/S for one company: the latest market
        close joined against the most recently reported annual diluted EPS
        and revenue. Both ratios are explicitly trailing; as-of dates for the
        price and the EPS/revenue are included so staleness is visible. Use
        this for any valuation/multiple question — never estimate a multiple
        from memory.

        Args:
            ticker: Stock ticker — one of NVDA, MSFT, AAPL, GOOGL, ETN.
        """
        ticker = ticker.upper()
        if ticker not in UNIVERSE:
            result = {"error": f"unknown ticker {ticker}, must be one of {UNIVERSE}"}
        else:
            result = _get_valuation(ticker) or {"error": f"no valuation data for {ticker}"}
        record("get_valuation", {"ticker": ticker}, result)
        return _dump(result)

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
        result = (
            {"error": f"unknown ticker {ticker}, must be one of {UNIVERSE}"}
            if ticker not in UNIVERSE
            else _get_capex_context(ticker)
        )
        record("get_capex_context", {"ticker": ticker}, result)
        return _dump(result)

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
        result = _search_filings(query, ticker=ticker, item=item, fiscal_year=fiscal_year)
        record(
            "search_filings",
            {"query": query, "ticker": ticker, "item": item, "fiscal_year": fiscal_year},
            result,
        )
        return _dump(result)

    return [get_fundamentals, compare_companies, get_valuation, get_capex_context, search_filings]
