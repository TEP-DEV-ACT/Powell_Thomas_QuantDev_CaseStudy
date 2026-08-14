"""Orchestrates a full live ingestion run: EDGAR facts -> normalize ->
prices -> FRED macro -> EDGAR filings/sections. Each step is independently
runnable too (python -m tracker.ingest.<module>); this just runs them in the
right order for a from-scratch or refresh pull from the live sources.

Run: python -m tracker.ingest.run_all
"""
import logging
import sys

from tracker.ingest import edgar_facts, edgar_filings, macro_fred, prices
from tracker.logging_config import configure_logging
from tracker.transform import normalize

logger = logging.getLogger(__name__)

# (label, step) — each step already records its own success/failure to
# ingest_runs via ingest/_runlog.py's track_run. One source being down (e.g.
# FRED unreachable) shouldn't block the others from ingesting, so a failure
# here is caught, logged, and the run continues — the final summary makes
# any failure visible without silently swallowing it.
STEPS = [
    ("edgar_facts", edgar_facts.run),
    ("normalize", normalize.run),
    ("prices", prices.run),
    ("macro_fred", macro_fred.run),
    ("edgar_filings (+ section extraction)", edgar_filings.run),
]


def run() -> bool:
    """Returns True iff every step succeeded."""
    failures = []
    for label, step in STEPS:
        logger.info("== %s ==", label)
        try:
            step()
        except Exception:
            logger.exception("Step failed: %s — continuing with remaining steps", label)
            failures.append(label)

    if failures:
        logger.error("Ingestion run finished with failures: %s", failures)
    else:
        logger.info("== done ==")
    return not failures


if __name__ == "__main__":
    configure_logging()
    ok = run()
    sys.exit(0 if ok else 1)
