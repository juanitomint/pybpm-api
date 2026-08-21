from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PermissionGroup(Base):
    """Mirrors the legacy MongoDB `perm.groups` collection.

    Grants a group access to a specific path within the BPM repository
    (e.g., ``root/modules/bpm``). One row per ``(group, path)`` pair.
    """

    __tablename__ = "permission_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # resource path (e.g. 'root/modules/bpm')
    idgroup: Mapped[int] = mapped_column(Integer(), ForeignKey("groups.idgroup"))
