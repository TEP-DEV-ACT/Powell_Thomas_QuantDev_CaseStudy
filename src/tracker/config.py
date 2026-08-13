"""Central configuration: the company universe, FRED series, and env loading.

Adding a ticker to the tracker is a one-line change here — CIKs are resolved
at runtime from SEC's company_tickers.json, never hardcoded.
"""
import os

from dotenv import load_dotenv

load_dotenv()

UNIVERSE = ["NVDA", "MSFT", "AAPL", "GOOGL", "ETN"]

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://tracker:tracker@localhost:5432/tracker"
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL") or None
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", "Thomas Powell thomaspowellhhe@outlook.com"
)

FRED_API_KEY = os.environ.get("FRED_API_KEY") or None

# FRED series backing the capex-cycle-beta metric.
# PNFI: Private Nonresidential Fixed Investment (quarterly, SAAR) — the reliable anchor.
# Y033RC1Q027SBEA: Private fixed investment in information processing equipment
#   (quarterly, SAAR) — confirmed against https://fred.stlouisfed.org/series/Y033RC1Q027SBEA.
FRED_SERIES = {
    "capex_anchor": "PNFI",
    "capex_info_processing": "Y033RC1Q027SBEA",
}

FLASK_PORT = int(os.environ.get("FLASK_PORT", "8000"))
