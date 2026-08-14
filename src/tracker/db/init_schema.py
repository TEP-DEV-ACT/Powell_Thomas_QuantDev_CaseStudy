"""CLI entrypoint: apply schema.sql. Run via `python -m tracker.db.init_schema`."""
from tracker.db.session import apply_schema
from tracker.logging_config import configure_logging

if __name__ == "__main__":
    configure_logging()
    apply_schema()
