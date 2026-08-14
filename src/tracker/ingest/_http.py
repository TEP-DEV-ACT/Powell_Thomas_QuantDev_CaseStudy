"""Shared HTTP session for ingestion: SEC-compliant User-Agent, rate limiting,
and retry/backoff. All EDGAR requests must go through this session — SEC
blocks requests without a descriptive User-Agent and polices request rate.
"""
import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from tracker.config import SEC_USER_AGENT

logger = logging.getLogger(__name__)

_MIN_INTERVAL = 1.0 / 10  # SEC fair-access policy: stay at or under 10 req/s
_last_request_at = 0.0


def _rate_limit():
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_at = time.monotonic()


def sec_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        }
    )
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


def get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    _rate_limit()
    logger.debug("GET %s", url)
    try:
        resp = session.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
    except Exception:
        logger.exception("GET %s failed", url)
        raise
    return resp
