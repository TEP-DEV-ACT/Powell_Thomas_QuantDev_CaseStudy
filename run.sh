#!/usr/bin/env bash
# Container entrypoint: apply schema, auto-load the committed seed if the DB
# is empty, then start the app. Live ingestion is a separate explicit command
# (python -m tracker.ingest.run_all), never triggered from here.
set -euo pipefail

python -m tracker.db.init_schema

if python -m tracker.ingest.seed --check-empty; then
    echo "Database empty — loading committed seed snapshot..."
    python -m tracker.ingest.seed --load
else
    echo "Database already has data — skipping seed load."
fi

exec gunicorn --bind 0.0.0.0:${FLASK_PORT:-8000} --workers 2 tracker.web.app:app
