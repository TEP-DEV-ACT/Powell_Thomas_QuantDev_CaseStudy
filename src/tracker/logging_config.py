"""Central logging setup.

The app has no external log aggregator, so alongside the usual console
output we keep the most recent records in memory — this is what backs the
/logs page in the web UI. Only meaningful within a single process: it does
not see output from separate CLI runs (e.g. `python -m tracker.ingest.run_all`).
"""
import logging
import os
from collections import deque
from datetime import datetime, timezone

_BUFFER_SIZE = 500
_buffer: deque = deque(maxlen=_BUFFER_SIZE)


class _RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _buffer.append(
            {
                "time": datetime.fromtimestamp(record.created, tz=timezone.utc),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            }
        )


def get_recent_logs() -> list:
    """Most recent log record first."""
    return list(reversed(_buffer))


def configure_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(h, _RingBufferHandler) for h in root.handlers):
        return  # already configured (e.g. Flask's reloader re-imports this module)

    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root.addHandler(console)

    ring = _RingBufferHandler()
    ring.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(ring)
