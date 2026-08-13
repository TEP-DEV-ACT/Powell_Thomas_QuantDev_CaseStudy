"""Orchestrates a full live ingestion run: EDGAR facts -> normalize ->
prices -> FRED macro -> EDGAR filings/sections. Each step is independently
runnable too (python -m tracker.ingest.<module>); this just runs them in the
right order for a from-scratch or refresh pull from the live sources.

Run: python -m tracker.ingest.run_all
"""
from tracker.ingest import edgar_facts, edgar_filings, macro_fred, prices
from tracker.transform import normalize


def run():
    print("== edgar_facts ==")
    edgar_facts.run()
    print("== normalize ==")
    normalize.run()
    print("== prices ==")
    prices.run()
    print("== macro_fred ==")
    macro_fred.run()
    print("== edgar_filings (+ section extraction) ==")
    edgar_filings.run()
    print("== done ==")


if __name__ == "__main__":
    run()
