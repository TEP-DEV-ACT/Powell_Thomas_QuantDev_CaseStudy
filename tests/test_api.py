"""Endpoint smoke tests against the (seeded) database — no network calls."""
import pytest

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
    assert tickers == {"NVDA", "MSFT", "AAPL", "GOOGL", "ETN"}


def test_fundamentals_endpoint(client):
    resp = client.get("/api/fundamentals/NVDA?years=3")
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


def test_valuation_endpoint(client):
    resp = client.get("/api/valuation/AAPL")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "trailing_pe" in body
    assert "trailing_ps" in body


def test_capex_endpoint(client):
    resp = client.get("/api/capex/MSFT")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ticker"] == "MSFT"
    assert isinstance(body["series"], list)


def test_prices_endpoint(client):
    resp = client.get("/api/prices/GOOGL?days=30")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert 0 < len(rows) <= 30


def test_filings_endpoint(client):
    resp = client.get("/api/filings/ETN")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) >= 1
    assert all(row["primary_doc_url"].startswith("https://www.sec.gov/") for row in rows)


def test_ask_endpoint_requires_question(client):
    resp = client.post("/api/ask", json={})
    assert resp.status_code == 400
