#!/usr/bin/env bash
set -euo pipefail

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Run alembic migrations
echo "Running database migrations..."
uv run alembic upgrade head

# Start the application
echo "Starting the application..."
exec uv run uvicorn main:app --host 0.0.0.0 --port ${APP_PORT:-5000} ${APP_EXTRA:""}
