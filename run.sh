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

# Single worker: the /logs page's in-memory buffer is per-process, so more
# than one worker would make it show a different, inconsistent slice of
# history depending on which worker happened to handle each request.
#
# --timeout 120: the chat agent can run several tool-use iterations, each a
# round trip to the Anthropic API, before it answers — that routinely exceeds
# gunicorn's 30s default. A timed-out worker is SIGABRT'd mid-request (a bare
# 500 with no JSON body) and restarting it also wipes the /logs ring buffer,
# so a slow turn looks like a silent, unlogged failure.
exec gunicorn --bind 0.0.0.0:${FLASK_PORT:-8000} --workers 1 --timeout 120 tracker.web.app:app
