"""RBAC (Role-Based Access Control) service."""

from __future__ import annotations

import logging

import sqlalchemy as sa
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

    async def put_path(
        self, path: str, properties: dict, idu: int | None = None
    ) -> PermissionRepository:
        """Upsert a path into permission_repository.

        Args:
            path: resource path.
            properties: dict with optional 'source', 'check_date'.
            idu: user ID who performed the action.
        """
        result = await self.db.execute(
            select(PermissionRepository).where(PermissionRepository.path == path)
        )
        entry = result.scalar_one_or_none()
        if entry is not None:
            entry.path = path
            entry.source = properties.get("source", entry.source)
            entry.check_date = properties.get("check_date", entry.check_date)
            if idu is not None:
                entry.idu = idu
        else:
            entry = PermissionRepository(
                path=path,
                source=properties.get("source"),
                idu=idu,
                check_date=properties.get("check_date"),
            )
            self.db.add(entry)

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

    async def add_path_to_group(
        self,
        path: str,
        idgroup: int,
        source: str = "api",
        updated_by: int | None = None,
    ) -> PermissionGroup:
        """Insert a path-to-group mapping.

        Replaces the old upsert logic: each call now inserts a fresh row
        so that updated_at/updated_by always reflect the latest change.
        """
        stmt = sa.insert(PermissionGroup).values(
            idgroup=idgroup, path=path, source=source, updated_by=updated_by
        )
        await self.db.execute(stmt)
        result = await self.db.execute(
            sa.select(PermissionGroup).where(
                PermissionGroup.idgroup == idgroup,
                PermissionGroup.path == path,
            )
        )
        return result.scalar_one()

    async def set_group_paths(
        self,
        idgroup: int,
        paths: list[str],
        source: str = "api",
        updated_by: int | None = None,
    ) -> list[str]:
        """Replace all paths for the group.

        Clears existing paths first, then inserts the new set.
        """
        await self.clear_paths(idgroup)
        for path in paths:
            await self.add_path_to_group(
                path, idgroup, source=source, updated_by=updated_by
            )
        await self.db.flush()
        await self.db.commit()
        return await self.get_group_paths(idgroup)

    async def has_path(self, idgroup: int, path: str) -> bool:
        """Check if a group has access to a path."""
        result = await self.db.execute(
            select(PermissionGroup.idgroup).where(
                PermissionGroup.idgroup == idgroup,
                PermissionGroup.path == path,
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_tree(
        self, node: str | None = None, sort: str | None = None
    ) -> list[dict]:
        """Return repository as nested tree structure (Ext JS tree format).

        Entries are stored as 'path:method' (e.g. 'GET /bpm/engine/execute').
        The tree is built by splitting route paths into segments. Leaf nodes
        carry the HTTP method in their data and use 'path:method' as their ID
        so the client's rec.data.id matches the DB format.
        """
        entries = await self.get_repository()

        # Build a nested dict tree (trie) from DB entries
        root: dict = {}
        for e in entries:
            raw = e.path
            colon_idx = raw.rfind(":")
            if colon_idx >= 0:
                route = raw[:colon_idx]
                method = raw[colon_idx + 1 :]
            else:
                route = raw
                method = ""

            data = {
                "source": e.source,
                "checkdate": e.check_date.strftime("%Y-%m-%d %H:%M:%S")
                if e.check_date
                else None,
                "idu": e.idu,
            }

            segments = [s for s in route.strip("/").split("/") if s]
            current = root
            current_node = None
            for i, seg in enumerate(segments):
                is_last = i == len(segments) - 1
                if seg not in current:
                    if is_last:
                        current[seg] = {
                            "text": seg,
                            "leaf": True,
                            "methods": {},
                        }
                    else:
                        current[seg] = {
                            "text": seg,
                            "leaf": False,
                            "children": {},
                        }
                elif current[seg].get("leaf") and not is_last:
                    # Existing leaf needs to become non-leaf (longer path passes through)
                    existing = current[seg]
                    current[seg] = {
                        "text": existing["text"],
                        "leaf": False,
                        "children": {},
                        "methods": existing.get("methods", {}),
                    }
                # Navigate: track the node and its child container separately
                trie_node = current[seg]
                current_node = trie_node
                current = trie_node if trie_node.get("leaf") else trie_node["children"]
            if method:
                if "methods" not in current_node:
                    current_node["methods"] = {}
                current_node["methods"][method] = data

        # Convert dict tree to list format
        def _to_list(tree: dict, prefix: str) -> list[dict]:
            result: list[dict] = []
            for key in sorted(tree.keys()):
                node = tree[key]
                child_prefix = f"{prefix}/{key}"
                if node["leaf"]:
                    if node["methods"]:
                        for method in sorted(node["methods"].keys()):
                            data = node["methods"][method]
                            result.append(
                                {
                                    "id": f"{child_prefix}:{method}".replace(
                                        "/", "\\/"
                                    ),
                                    "text": f"{key}:{method}",
                                    "leaf": True,
                                    "checked": False,
                                    "expanded": False,
                                    "iconCls": "dot-green",
                                    "data": data,
                                }
                            )
                    else:
                        result.append(
                            {
                                "id": child_prefix.replace("/", "\\/"),
                                "text": key,
                                "leaf": True,
                                "checked": False,
                                "expanded": False,
                            }
                        )
                else:
                    child_list = _to_list(node["children"], child_prefix)
                    result.append(
                        {
                            "id": child_prefix.replace("/", "\\/"),
                            "text": key,
                            "leaf": False,
                            "checked": False,
                            "expanded": False,
                            "children": child_list,
                        }
                    )
                    # Also show method leaves for this node
                    if node.get("methods"):
                        for method in sorted(node["methods"].keys()):
                            data = node["methods"][method]
                            child_list.append(
                                {
                                    "id": f"{child_prefix}:{method}".replace(
                                        "/", "\\/"
                                    ),
                                    "text": f"{key}:{method}",
                                    "leaf": True,
                                    "checked": False,
                                    "expanded": False,
                                    "iconCls": "dot-green",
                                    "data": data,
                                }
                            )
            return result

        if node == "root" or node is None:
            return _to_list(root, "root")

        # Lazy load: find the node in the trie and return its children
        target_path = node.rstrip("/")
        parts = [s for s in target_path.split("/") if s]
        current = root
        for part in parts:
            if part in current:
                current = current[part]
            else:
                return []

        if current.get("leaf"):
            return []

        children = _to_list(current.get("children", {}), target_path)

        # Parse sort param
        if sort:
            try:
                import json

                sorters = json.loads(sort)
            except (json.JSONDecodeError, TypeError):
                sorters = []
            if sorters:
                for s in reversed(sorters):
                    prop = s.get("property", "text")
                    direction = s.get("direction", "ASC")
                    reverse = direction == "DESC"
                    if prop == "text":
                        children.sort(key=lambda c: c["text"], reverse=reverse)
        return children
