"""CLI entrypoint: apply schema.sql. Run via `python -m tracker.db.init_schema`."""
from tracker.db.session import apply_schema

if __name__ == "__main__":
    apply_schema()
    print("Schema applied.")
