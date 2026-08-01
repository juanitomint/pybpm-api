from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models.

    Exposes ``metadata`` for Alembic autogenerate and provides the standard
    ``query``, ``insert``, etc. classmethods from DeclarativeBase.
    """

