FROM python:3.14-slim AS base

ENV LOG_FORMATTER=json \
    DEBIAN_FRONTEND=noninteractive
ENV APP_PORT=5000
ENV APP_EXTRA=""

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

FROM deps AS runtime
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=deps /app/.venv /.venv
COPY . .
EXPOSE ${APP_PORT}
CMD ["/app/boot.sh"]
