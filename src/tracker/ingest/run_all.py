"""Orchestrates a full live ingestion run: EDGAR facts -> normalize ->
prices -> FRED macro -> EDGAR filings/sections. Each step is independently
runnable too (python -m tracker.ingest.<module>); this just runs them in the
right order for a from-scratch or refresh pull from the live sources.

Run: python -m tracker.ingest.run_all
"""
import logging

from tracker.ingest import edgar_facts, edgar_filings, macro_fred, prices
from tracker.logging_config import configure_logging
from tracker.transform import normalize

logger = logging.getLogger(__name__)


def run():
    logger.info("== edgar_facts ==")
    edgar_facts.run()
    logger.info("== normalize ==")
    normalize.run()
    logger.info("== prices ==")
    prices.run()
    logger.info("== macro_fred ==")
    macro_fred.run()
    logger.info("== edgar_filings (+ section extraction) ==")
    edgar_filings.run()
    logger.info("== done ==")


if __name__ == "__main__":
    configure_logging()
    run()
