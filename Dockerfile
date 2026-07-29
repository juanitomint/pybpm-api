FROM python:3.14-slim AS base

ENV LOG_FORMATTER=json \
    FLASK_APP=app.py \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --quiet uv

FROM base AS deps
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync

FROM base AS runtime
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=deps /app/.venv /.venv
COPY . .
EXPOSE 5000
CMD ["/app/boot.sh"]
