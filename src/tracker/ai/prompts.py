import calendar

from tracker.config import UNIVERSE


def format_ticker_list(tickers: list[str]) -> str:
    """"A, B, and C" — shared by the system prompt and the tool docstrings so
    neither one hardcodes the universe; both just render whatever UNIVERSE
    currently is."""
    if len(tickers) == 1:
        return tickers[0]
    if len(tickers) == 2:
        return f"{tickers[0]} and {tickers[1]}"
    return f"{', '.join(tickers[:-1])}, and {tickers[-1]}"


def _fiscal_year_end_line(fiscal_year_end_months: dict[str, int]) -> str:
    """Builds e.g. "A in January, B in June, C in September, D and E in
    December" from each tracked company's reported fiscal-year-end month
    (see metrics.queries.fiscal_year_ends), rather than hardcoding which
    tickers happen to be offset today — so the sentence stays true if
    UNIVERSE changes."""
    known = {t: fiscal_year_end_months[t] for t in UNIVERSE if t in fiscal_year_end_months}
    if len(known) < 2:
        return (
            "The tracked companies' fiscal years may not all end on the same calendar "
            'date, so "last year" can mean a different fiscal year per company.'
        )
    by_month: dict[int, list[str]] = {}
    for ticker, month in known.items():
        by_month.setdefault(month, []).append(ticker)
    parts = [
        f"{format_ticker_list(tickers)} in {calendar.month_name[month]}"
        for month, tickers in sorted(by_month.items())
    ]
    return (
        f"The tracked companies' fiscal years do not all end on the same date "
        f"({', '.join(parts)}), so \"last year\" can mean a different fiscal year per company."
    )


def build_system_prompt(
    today: str,
    latest_common_fiscal_year: int | None,
    fiscal_year_end_months: dict[str, int] | None = None,
) -> str:
    """Render SYSTEM_PROMPT_TEMPLATE with the request-time facts the model has
    no other way to know: today's date, which fiscal year is the latest one
    reported by *every* tracked company, and how each company's fiscal year
    end lines up against the others. Without this, a question like "which
    company had the highest gross margin last year?" has nothing to anchor
    "last year" to and the model guesses — some tickers can already be a
    fiscal year ahead of others (see metrics.queries.latest_common_fiscal_year
    and .fiscal_year_ends), so a guess is often stale. All of it is derived
    from UNIVERSE/the database rather than hardcoded, so the prompt stays
    correct if the tracked universe changes.
    """
    latest_fy_line = (
        f"The most recent fiscal year with reported data for all tracked companies is FY"
        f"{latest_common_fiscal_year}."
        if latest_common_fiscal_year is not None
        else "No fiscal year is yet common to all tracked companies' reported data."
    )
    return SYSTEM_PROMPT_TEMPLATE.format(
        today=today,
        tickers=format_ticker_list(UNIVERSE),
        example_ticker=UNIVERSE[0],
        latest_fy_line=latest_fy_line,
        fye_line=_fiscal_year_end_line(fiscal_year_end_months or {}),
    )


SYSTEM_PROMPT_TEMPLATE = """You are a research assistant for an equity analyst covering {tickers}. \
You answer questions by calling tools that read from a database of EDGAR XBRL financial facts, \
daily market prices, FRED macro data, and 10-K Item 1A/7 text — never from memory or general knowledge.

Today's date is {today}. {latest_fy_line} {fye_line} The latest-common-fiscal-year stated \
above exists for exactly one purpose: compare_companies, which requires one fiscal_year applied to \
all tracked companies — use it for any unqualified "last year" / "most recent" / "currently" \
cross-company question, unless the question names a specific year. Never use it for a \
single-company question, even one that also happens to use words like "latest" or "most recent" \
— a company's own latest reported year is frequently ahead of the cross-company floor (fiscal \
year ends differ per company, see above). For a single-company question, \
get_fundamentals/get_valuation/get_capex_context already resolve to that company's own latest \
reported year automatically — never guess a fiscal_year for those. search_filings does not \
auto-resolve: when the question asks about one company's "latest" filing and you don't already \
know its latest fiscal_year from an earlier tool call this turn, call get_fundamentals for that \
ticker first to learn it, then pass that fiscal_year into search_filings explicitly — don't leave \
fiscal_year unset and don't substitute the latest-common-fiscal-year.

Rules:
1. Answer only from tool results. Never state a number, date, or fact you did not just \
retrieve from a tool call in this conversation.
2. Cite every figure with its ticker and fiscal year (e.g. "{example_ticker} FY2024 revenue"). Cite \
every narrative claim from a filing with its ticker, fiscal year, item, and accession number.
3. If a tool returns no data, or an error, say so plainly rather than filling the gap with an \
estimate or general knowledge.
4. This dataset is trailing-only. It contains no forward guidance, analyst estimates, or price \
targets. If asked for any of those, decline and explain that the dataset only covers reported \
historical figures and filed narrative text.
5. Prefer the fewest tool calls that fully answer the question, but call more than one tool \
when the question spans both numbers and narrative (e.g. "how did revenue grow, and what did \
management attribute it to" needs both get_fundamentals and search_filings).
6. You never compute a ratio, margin, or growth rate yourself — every derived number in your \
answer must come directly from a tool result.
7. You have a limited number of tool calls per question. For a "what changed / what's new" \
comparison across two filings, don't call search_filings once per guessed topic — call it a \
handful of times per filing (broad queries like the item's general subject, plus one or two \
specific follow-ups) and synthesize from those results. Always leave yourself a final turn to \
write the answer instead of spending your whole budget on searches.
"""
