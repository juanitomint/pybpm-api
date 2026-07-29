#!/usr/bin/env bash
set -euo pipefail

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Run alembic migrations
echo "Running database migrations..."
uv run alembic upgrade head

# Start the application (assuming it's a FastAPI app now, or similar)
echo "Starting the application..."
uv run uvicorn app:create_app --host 0.0.0.0 --port 5000 --reload
