from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    idu: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nick: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    pass_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    lastname: Mapped[str | None] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(255))
    avatar: Mapped[bytes | None] = mapped_column(sa.LargeBinary())
    token: Mapped[str | None] = mapped_column(String(255), unique=True)
    last_acc: Mapped[datetime | None] = mapped_column(DateTime)
