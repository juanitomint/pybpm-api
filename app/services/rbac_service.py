"""RBAC (Role-Based Access Control) service."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission_group import PermissionGroup
from app.models.permission_repository import PermissionRepository

logger = logging.getLogger(__name__)


class RbacService:
    """Business logic for RBAC: permission repository and group paths."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_repository(self) -> list[PermissionRepository]:
        """Return all permission_repository entries."""
        result = await self.db.execute(select(PermissionRepository))
        return list(result.scalars().all())

    async def put_path(self, path: str, properties: dict) -> PermissionRepository:
        """Upsert a path into permission_repository."""
        result = await self.db.execute(
            select(PermissionRepository).where(PermissionRepository.path == path)
        )
        entry = result.scalar_one_or_none()
        if entry is not None:
            entry.path = path
            entry.source = properties.get("source", entry.source)
            entry.check_date = properties.get("check_date", entry.check_date)
        else:
            entry = PermissionRepository(
                path=path,
                source=properties.get("source"),
                check_date=properties.get("check_date"),
            )
            self.db.add(entry)
        await self.db.flush()
        return entry

    async def remove_path(self, path: str) -> bool:
        """Remove a path from permission_repository."""
        result = await self.db.execute(
            select(PermissionRepository).where(PermissionRepository.path == path)
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return False
        await self.db.delete(entry)
        await self.db.flush()
        return True

    async def get_group_paths(self, idgroup: int) -> list[str]:
        """Return paths for a group from permission_groups."""
        result = await self.db.execute(
            select(PermissionGroup.path).where(PermissionGroup.idgroup == idgroup)
        )
        return list(result.scalars().all())

    async def clear_paths(self, idgroup: int) -> int:
        """Delete all permission_groups entries for a group, return count."""
        result = await self.db.execute(
            select(PermissionGroup).where(PermissionGroup.idgroup == idgroup)
        )
        entries = list(result.scalars().all())
        count = len(entries)
        for entry in entries:
            await self.db.delete(entry)
        await self.db.flush()
        return count

    async def add_path_to_group(self, path: str, idgroup: int) -> PermissionGroup:
        """Add (upsert) a path-to-group mapping."""
        result = await self.db.execute(
            select(PermissionGroup).where(
                PermissionGroup.idgroup == idgroup,
                PermissionGroup.path == path,
            )
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            entry = PermissionGroup(idgroup=idgroup, path=path)
            self.db.add(entry)
        await self.db.flush()
        return entry

    async def set_group_paths(self, idgroup: int, paths: list[str]) -> list[str]:
        """Clear existing paths, add new ones, return final list."""
        await self.clear_paths(idgroup)
        for path in paths:
            await self.add_path_to_group(path, idgroup)
        return await self.get_group_paths(idgroup)

    async def has_path(self, idgroup: int, path: str) -> bool:
        """Check if a group has access to a path."""
        result = await self.db.execute(
            select(PermissionGroup.id).where(
                PermissionGroup.idgroup == idgroup,
                PermissionGroup.path == path,
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_tree(
        self, node: str | None = None, sort: str | None = None
    ) -> list[dict]:
        """Return repository as nested tree structure (Ext JS format).

        Args:
            node: node id to load children for ("root" = full tree).
            sort: Ext JS sort param — JSON array of {property, direction}.
        """
        entries = await self.get_repository()

        # Parse sort param if provided
        sorters = []
        if sort:
            try:
                import json
                sorters = json.loads(sort)
            except (json.JSONDecodeError, TypeError):
                sorters = []

        if sorters:
            for s in reversed(sorters):
                prop = s.get("property", "path")
                direction = s.get("direction", "ASC")
                reverse = direction == "DESC"
                if prop == "path":
                    entries = sorted(entries, key=lambda e: e.path, reverse=reverse)

        if node == "root" or node is None:
            # Return full tree from root
            root: dict[str, Any] = {"text": "root", "id": "root", "children": [], "expanded": True}

            for entry in entries:
                parts = entry.path.strip("/").split("/")
                current = root
                for i, part in enumerate(parts):
                    children = current.setdefault("children", [])
                    existing = next(
                        (c for c in children if c["text"] == part), None
                    )
                    if existing:
                        current = existing
                    else:
                        is_leaf = (i == len(parts) - 1)
                        full_path = "/".join(parts[: i + 1])
                        new_node = {
                            "id": full_path,
                            "text": part,
                            "leaf": is_leaf,
                            "cls": "dot-green" if is_leaf else "",
                            "expanded": not is_leaf,
                        }
                        if "children" not in new_node:
                            new_node["children"] = []
                        children.append(new_node)
                        current = new_node

            return [root]

        # Return children of a specific node
        target_path = node.rstrip("/")
        children: list[dict] = []
        seen: set[str] = set()

        for entry in entries:
            path = entry.path.strip("/")
            if not path.startswith(target_path + "/"):
                continue
            rest = path[len(target_path) + 1:]
            top = rest.split("/")[0]
            if top not in seen:
                seen.add(top)
                children.append({
                    "id": f"{target_path}/{top}",
                    "text": top,
                    "leaf": "/" not in rest,
                    "cls": "dot-green" if "/" not in rest else "",
                    "expanded": False,
                })

        if sorters:
            for s in reversed(sorters):
                prop = s.get("property", "text")
                direction = s.get("direction", "ASC")
                reverse = direction == "DESC"
                if prop == "text":
                    children = sorted(children, key=lambda c: c["text"], reverse=reverse)

        return children
