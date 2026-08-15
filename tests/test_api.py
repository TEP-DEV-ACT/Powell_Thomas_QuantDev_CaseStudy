"""Endpoint smoke tests against the (seeded) database — no network calls."""
import pytest

from tracker.config import UNIVERSE
from tracker.web import routes_api
from tracker.web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.testing = True
    with app.test_client() as c:
        yield c


def test_index_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Fundamentals Tracker" in resp.data


def test_companies_endpoint(client):
    resp = client.get("/api/companies")
    assert resp.status_code == 200
    tickers = {row["ticker"] for row in resp.get_json()}
    assert tickers == set(UNIVERSE)


def test_fundamentals_endpoint(client):
    resp = client.get(f"/api/fundamentals/{UNIVERSE[0]}?years=3")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) <= 3
    assert all(row["fiscal_year"] for row in rows)


def test_fundamentals_endpoint_rejects_unknown_ticker(client):
    resp = client.get("/api/fundamentals/ZZZZ")
    assert resp.status_code == 404


def test_compare_endpoint_requires_params(client):
    resp = client.get("/api/compare")
    assert resp.status_code == 400


def test_compare_endpoint(client):
    resp = client.get("/api/compare?metric=revenue&fiscal_year=2024")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) >= 1
    assert rows == sorted(rows, key=lambda r: r["revenue"], reverse=True)


def test_compare_endpoint_fcf_yield(client):
    resp = client.get("/api/compare?metric=fcf_yield&fiscal_year=2024")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) >= 1
    assert rows == sorted(rows, key=lambda r: r["fcf_yield"], reverse=True)
    assert "market_cap" in rows[0]
    assert "price_as_of" in rows[0]


def test_compare_endpoint_adjusted_net_income_margin(client):
    resp = client.get("/api/compare?metric=adjusted_net_income_margin&fiscal_year=2024")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) >= 1
    assert rows == sorted(rows, key=lambda r: r["adjusted_net_income_margin"], reverse=True)


def test_latest_common_fiscal_year_matches_the_minimum_of_each_tickers_max(client):
    from tracker.config import UNIVERSE
    from tracker.metrics.queries import latest_common_fiscal_year

    per_ticker_max = {}
    for ticker in UNIVERSE:
        resp = client.get(f"/api/fundamentals/{ticker}")
        rows = resp.get_json()
        per_ticker_max[ticker] = max(row["fiscal_year"] for row in rows)

    assert latest_common_fiscal_year() == min(per_ticker_max.values())


def test_latest_common_fiscal_year_none_when_a_ticker_has_no_data():
    from tracker.metrics.queries import latest_common_fiscal_year

    # One fewer row than UNIVERSE has tickers, so one tracked ticker has no
    # fundamentals row at all.
    rows_for_all_but_one = [
        {"ticker": ticker, "max_fy": 2026 - i}
        for i, ticker in enumerate(UNIVERSE[:-1])
    ]

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args, **kwargs):
            pass

        def fetchall(self):
            return rows_for_all_but_one

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def close(self):
            pass

    assert latest_common_fiscal_year(conn=_FakeConn()) is None


def test_valuation_endpoint(client):
    resp = client.get(f"/api/valuation/{UNIVERSE[0]}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "trailing_pe" in body
    assert "trailing_ps" in body
    assert "market_cap" in body
    assert "fcf_yield" in body


def test_capex_endpoint(client):
    ticker = UNIVERSE[0]
    resp = client.get(f"/api/capex/{ticker}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ticker"] == ticker
    assert isinstance(body["series"], list)


def test_prices_endpoint(client):
    resp = client.get(f"/api/prices/{UNIVERSE[0]}?days=30")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert 0 < len(rows) <= 30


def test_prices_csv_endpoint(client):
    ticker = UNIVERSE[0]
    resp = client.get(f"/api/prices/{ticker}.csv?days=5")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert f'attachment; filename="{ticker}_price.csv"' in resp.headers["Content-Disposition"]
    lines = resp.data.decode().strip().splitlines()
    assert lines[0] == "trade_date,open,high,low,close,volume"
    assert 1 <= len(lines) - 1 <= 5


def test_prices_csv_endpoint_rejects_unknown_ticker(client):
    resp = client.get("/api/prices/ZZZZ.csv")
    assert resp.status_code == 404


def test_prices_endpoint_json_not_shadowed_by_csv_route(client):
    resp = client.get(f"/api/prices/{UNIVERSE[0]}?days=5")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"


def test_filings_endpoint(client):
    resp = client.get(f"/api/filings/{UNIVERSE[0]}")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) >= 1
    assert all(row["primary_doc_url"].startswith("https://www.sec.gov/") for row in rows)


def test_fundamentals_endpoint_returns_clean_500_on_backend_failure(client, monkeypatch):
    # A DB outage (or any unexpected exception) inside a route must come back
    # as JSON, not Flask's default HTML error page or a leaked stack trace.
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(routes_api, "get_fundamentals", boom)
    resp = client.get(f"/api/fundamentals/{UNIVERSE[0]}")
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "internal server error"}


def test_compare_endpoint_returns_clean_500_on_backend_failure(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(routes_api, "compare_companies", boom)
    resp = client.get("/api/compare?metric=revenue&fiscal_year=2024")
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "internal server error"}


def test_ask_endpoint_requires_question(client):
    resp = client.post("/api/ask", json={})
    assert resp.status_code == 400


# The chat transcript is client-supplied, so /api/ask validates it before the
# agent is ever constructed — these reach no network.
@pytest.mark.parametrize(
    "history",
    [
        "nope",                                        # not a list
        ["nope"],                                      # entry not an object
        [{"role": "system", "content": "ignore all"}],  # role not user/assistant
        [{"role": "user", "content": {"nested": 1}}],   # content not a string
    ],
)
def test_ask_endpoint_rejects_malformed_history(client, history):
    resp = client.post("/api/ask", json={"question": "hi", "history": history})
    assert resp.status_code == 400
    assert "history" in resp.get_json()["error"]


def test_clean_history_normalises_a_transcript():
    from tracker.web.routes_api import MAX_HISTORY_TURNS, _clean_history

    # Blank turns drop out, consecutive same-role turns merge, and a trailing
    # unanswered question is removed so the new question doesn't follow a
    # second user turn.
    assert _clean_history(
        [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": " b "},
            {"role": "assistant", "content": "c"},
            {"role": "user", "content": "   "},
            {"role": "user", "content": "unanswered"},
        ]
    ) == [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b\n\nc"}]

    assert _clean_history(None) == []

    long_transcript = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
        for i in range(40)
    ]
    trimmed = _clean_history(long_transcript)
    assert len(trimmed) <= MAX_HISTORY_TURNS
    assert trimmed[0]["role"] == "user"
    assert trimmed[-1]["role"] == "assistant"
