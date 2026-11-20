#!/bin/sh
# Web service entrypoint: migrate as the owner, then serve as kazi_app.
set -eu

if [ -n "${MIGRATIONS_DATABASE_URL:-}" ]; then
    alembic upgrade head
fi
# The app process never sees the owner credentials.
unset MIGRATIONS_DATABASE_URL

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --limit-concurrency 64 \
    --timeout-keep-alive 5 \
    --no-server-header \
    --no-access-log \
    --timeout-graceful-shutdown 10
