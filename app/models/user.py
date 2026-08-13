from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    idu: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nick: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    pass_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # MongoDB 'passw' — bcrypt hash
    name: Mapped[str | None] = mapped_column(String(128))
    lastname: Mapped[str | None] = mapped_column(String(128))
    perm: Mapped[list | None] = mapped_column(sa.JSON())  # MongoDB 'perm' — list of permission strings (e.g. ['ADM'])
    idgroup: Mapped[int | None] = mapped_column(Integer, index=True)  # MongoDB 'idgroup'
    last_acc: Mapped[datetime | None] = mapped_column("last_acc", DateTime(timezone=True))  # MongoDB 'lastacc' — last login timestamp
    email: Mapped[str | None] = mapped_column(String(255))
    avatar: Mapped[bytes | None] = mapped_column(sa.LargeBinary())
    token: Mapped[str | None] = mapped_column(String(255), unique=True)
