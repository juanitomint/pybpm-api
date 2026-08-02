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
exec uv run uvicorn main:app --host 0.0.0.0 --port 5000 --reload --reload-dir /app
