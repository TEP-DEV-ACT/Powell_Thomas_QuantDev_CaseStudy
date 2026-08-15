"""A DB/network failure inside an AI tool must degrade to a structured
{"error": ...} result the model can relay, never an unhandled exception that
aborts the whole chat turn (ai/tools.py's _safe wrapper). Pure unit tests —
monkeypatch the underlying metrics/search functions, no DB or Anthropic API.
"""
import json

import tracker.ai.tools as tools_module
from tracker.ai.tools import build_tools
from tracker.config import UNIVERSE

TICKER = UNIVERSE[0]


def _tool(name: str):
    by_name = {t.name: t for t in build_tools([])}
    return by_name[name]


def test_get_fundamentals_tool_survives_a_backend_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tools_module, "_get_fundamentals", boom)
    result = json.loads(_tool("get_fundamentals").func(ticker=TICKER))
    assert "error" in result


def test_compare_companies_tool_survives_a_backend_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tools_module, "_compare_companies", boom)
    result = json.loads(_tool("compare_companies").func(metric="net_income_margin", fiscal_year=2024))
    assert "error" in result


def test_get_valuation_tool_survives_a_backend_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tools_module, "_get_valuation", boom)
    result = json.loads(_tool("get_valuation").func(ticker=TICKER))
    assert "error" in result


def test_get_capex_context_tool_survives_a_backend_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tools_module, "_get_capex_context", boom)
    result = json.loads(_tool("get_capex_context").func(ticker=TICKER))
    assert "error" in result


def test_search_filings_tool_survives_a_backend_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tools_module, "_search_filings", boom)
    result = json.loads(_tool("search_filings").func(query="risk factors"))
    assert "error" in result


def test_trace_still_records_the_failed_call(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tools_module, "_get_fundamentals", boom)
    trace: list = []
    tool = {t.name: t for t in build_tools(trace)}["get_fundamentals"]
    tool.func(ticker=TICKER)
    assert len(trace) == 1
    assert trace[0]["tool"] == "get_fundamentals"
    assert "error" in trace[0]["result"]


def test_a_known_no_data_result_is_not_treated_as_a_crash(monkeypatch):
    # get_valuation legitimately returns None for missing data — that's not
    # an exception, and should surface as a normal {"error": ...} result,
    # not the generic "internal data error" message from the except branch.
    monkeypatch.setattr(tools_module, "_get_valuation", lambda ticker: None)
    result = json.loads(_tool("get_valuation").func(ticker=TICKER))
    assert result == {"error": f"no valuation data for {TICKER}"}
