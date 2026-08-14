"""Helper to record ingest_runs rows around an ingestion step."""
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@contextmanager
def track_run(conn, source: str):
    state = {"row_count": 0, "notes": None}
    started_at = datetime.now(timezone.utc)
    logger.info("ingest run started: %s", source)
    try:
        yield state
        status = "ok"
    except Exception as exc:
        status = "error"
        state["notes"] = f"{state['notes'] or ''} error={exc}".strip()
        logger.exception("ingest run failed: %s", source)
        raise
    finally:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingest_runs (source, started_at, finished_at, status, row_count, notes)
                VALUES (%(source)s, %(started_at)s, %(finished_at)s, %(status)s, %(row_count)s, %(notes)s)
                """,
                {
                    "source": source,
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc),
                    "status": status,
                    "row_count": state["row_count"],
                    "notes": state["notes"],
                },
            )
        conn.commit()
        logger.info("ingest run finished: %s status=%s rows=%d", source, status, state["row_count"])
