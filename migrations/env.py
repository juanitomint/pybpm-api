import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import (  # noqa: F401 — registers all models with db.metadata
    BpmModel,
    User,
)
from config import Config

# Import the Base so Alembic can see all model metadata for autogenerate.
from extensions import Base

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    url = Config.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    url = Config.DATABASE_URL
    connectable = engine_from_config(
        {"url": url},
        prefix="",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
