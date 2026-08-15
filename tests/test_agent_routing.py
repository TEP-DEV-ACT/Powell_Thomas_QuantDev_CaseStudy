"""Routing test for the six PDF questions — asserts which tools fire, and
that the forward-guidance question is declined rather than invented. Makes
real Anthropic API calls, so it needs ANTHROPIC_API_KEY and a populated DB;
skipped automatically if the key isn't set (e.g. in an offline CI run).
"""
import pytest

from tracker.config import ANTHROPIC_API_KEY, UNIVERSE

pytestmark = pytest.mark.skipif(not ANTHROPIC_API_KEY, reason="ANTHROPIC_API_KEY not set")


def _tools_used(result):
    return [t["tool"] for t in result["trace"]]


def _inputs_for(result, tool_name):
    return [t["input"] for t in result["trace"] if t["tool"] == tool_name]


def test_structured_question_uses_get_fundamentals():
    from tracker.ai.agent import ask

    ticker = UNIVERSE[0]
    result = ask(f"What were {ticker}'s revenue and net income for the last three fiscal years?")
    assert "get_fundamentals" in _tools_used(result)
    assert result["answer"]


def test_comparative_question_uses_compare_companies():
    from tracker.ai.agent import ask
    from tracker.metrics.queries import latest_common_fiscal_year

    result = ask("Which of the tracked companies had the highest gross margin last year?")
    assert "compare_companies" in _tools_used(result)
    # Not just which tool fired — an unqualified "last year" must resolve to
    # the latest fiscal year common to all tracked companies, not a stale
    # guess (this regressed once: the model picked a stale fiscal year while
    # later data already existed, because it had no way to know what
    # "latest" meant).
    expected_fy = latest_common_fiscal_year()
    fiscal_years_asked = [i["fiscal_year"] for i in _inputs_for(result, "compare_companies")]
    assert expected_fy in fiscal_years_asked


def test_cross_source_question_uses_get_valuation():
    from tracker.ai.agent import ask

    ticker = UNIVERSE[1 % len(UNIVERSE)]
    result = ask(f"What is {ticker}'s trailing P/E right now?")
    assert "get_valuation" in _tools_used(result)


def test_filing_text_question_uses_search_filings():
    from tracker.ai.agent import ask

    ticker = UNIVERSE[0]
    result = ask(f"What new risk factors did {ticker} add in its latest 10-K versus the prior year?")
    assert "search_filings" in _tools_used(result)


def test_cross_modal_question_uses_both_numbers_and_text():
    from tracker.ai.agent import ask

    ticker = UNIVERSE[1 % len(UNIVERSE)]
    result = ask(f"How did {ticker}'s revenue grow last year, and what did management attribute it to?")
    tools = _tools_used(result)
    assert "get_fundamentals" in tools
    assert "search_filings" in tools


def test_forward_guidance_question_is_declined_not_invented():
    from tracker.ai.agent import ask

    result = ask("What is the company's forward guidance for next quarter?")
    assert _tools_used(result) == []
    answer_lower = result["answer"].lower()
    assert any(word in answer_lower for word in ["can't", "cannot", "don't have", "no forward", "trailing"])
