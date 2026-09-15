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

    async def put_path(self, path: str, properties: dict, idu: int | None = None) -> PermissionRepository:
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

    async def add_path_to_group(self, path: str, idgroup: int, source: str = "api") -> PermissionGroup:
        """Add (upsert) a path-to-group mapping."""
        result = await self.db.execute(
            select(PermissionGroup).where(
                PermissionGroup.idgroup == idgroup,
                PermissionGroup.path == path,
            )
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            entry = PermissionGroup(idgroup=idgroup, path=path, source=source)
            self.db.add(entry)
        await self.db.flush()
        return entry

    async def set_group_paths(self, idgroup: int, paths: list[str], source: str = "api") -> list[str]:
        """Clear existing paths, add new ones, return final list."""
        await self.clear_paths(idgroup)
        for path in paths:
            await self.add_path_to_group(path, idgroup, source=source)
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
        """Return repository as nested tree structure (Ext JS tree format).

        Entries are stored as 'path:method' (e.g. 'GET /bpm/engine/execute').
        The tree is built by splitting route paths into segments. Leaf nodes
        carry the HTTP method in their data and use 'path:method' as their ID
        so the client's rec.data.id matches the DB format.
        """
        entries = await self.get_repository()

        # Parse entries into (route_path, method, data) tuples
        parsed: list[tuple[str, str, dict[str, Any]]] = []
        for e in entries:
            raw = e.path
            colon_idx = raw.rfind(":")
            if colon_idx >= 0:
                route = raw[:colon_idx]
                method = raw[colon_idx + 1:]
            else:
                route = raw
                method = ""
            parsed.append((route, method, {
                "source": e.source,
                "checkdate": e.check_date.strftime("%Y-%m-%d %H:%M:%S") if e.check_date else None,
                "idu": e.idu,
            }))

        # Group by route path for method-level children
        route_groups: dict[str, list[tuple[str, dict]]] = {}
        for route, method, data in parsed:
            route_groups.setdefault(route, []).append((method, data))

        # Build a lookup: full path (with method) -> data
        entry_map: dict[str, dict[str, Any]] = {}
        for route, method, data in parsed:
            key = f"{route}:{method}" if method else route
            entry_map[key] = data

        # Parse sort param
        sorters: list[dict[str, str]] = []
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
                    parsed.sort(key=lambda x: x[0], reverse=reverse)

        def _build_children(parent_path: str, depth: int, is_root: bool = False, db_prefix: str | None = None) -> list[dict]:
            """Recursively build children for a given parent path."""
            children_map: dict[str, list[tuple[str, str, dict]]] = {}

            if is_root:
                for route, method, data in parsed:
                    if not route.strip("/"):
                        continue
                    top = route.strip("/").split("/")[0]
                    children_map.setdefault(top, []).append((route, method, data))
            elif db_prefix:
                prefix = db_prefix.rstrip("/") + "/"
                for route, method, data in parsed:
                    route_cmp = route.lstrip("/")
                    if not route_cmp.startswith(prefix.lstrip("/")):
                        continue
                    rest = route_cmp[len(prefix.lstrip("/")):]
                    top = rest.split("/")[0] if rest else ""
                    children_map.setdefault(top, []).append((route, method, data))
            else:
                prefix = parent_path.rstrip("/") + "/"
                for route, method, data in parsed:
                    route_cmp = route.lstrip("/")
                    if not route_cmp.startswith(prefix.lstrip("/")):
                        continue
                    rest = route_cmp[len(prefix.lstrip("/")):]
                    top = rest.split("/")[0] if rest else ""
                    children_map.setdefault(top, []).append((route, method, data))

            result: list[dict] = []
            for top_name in sorted(children_map.keys()):
                items = children_map[top_name]

                # Determine if this node has children or is a leaf with method children
                has_path_children = False
                has_method_children = False
                for route, method, data in items:
                    rest = route.strip("/").split("/")
                    if len(rest) > depth + 1:
                        has_path_children = True
                    if method:
                        has_method_children = True

                child_path = f"{parent_path}/{top_name}"
                has_children = has_path_children or has_method_children

                # Check for direct repo entry on this node
                node_data: dict[str, Any] | None = None
                if child_path in entry_map:
                    node_data = entry_map[child_path]

                node: dict[str, Any] = {
                    "id": child_path,
                    "text": top_name,
                    "leaf": not has_children,
                    "checked": False,
                    "expanded": False,
                }

                if node_data:
                    node["iconCls"] = "dot-green"
                    node["data"] = node_data
                elif has_children:
                    node["iconCls"] = "dot-green"

                if has_children:
                    # If has path children, recurse; otherwise show methods as children
                    if has_path_children:
                        node["children"] = _build_children(
                            child_path, depth + 1,
                            db_prefix=child_path[5:] if child_path.startswith("root/") else child_path,
                        )
                    else:
                        # No more path children — show methods as leaf nodes
                        # Each method gets its own leaf with DB-format ID (strip root/ prefix)
                        method_groups: dict[str, dict] = {}
                        for route, method, data in items:
                            if method:
                                method_groups.setdefault(method, data)
                        leaf_prefix = "/" + child_path[5:] if child_path.startswith("root/") else child_path
                        node["children"] = []
                        for method in sorted(method_groups.keys()):
                            node["children"].append({
                                "id": f"{leaf_prefix}:{method}",
                                "text": method,
                                "leaf": True,
                                "checked": False,
                                "expanded": False,
                                "iconCls": "dot-green",
                                "data": method_groups[method],
                            })

                result.append(node)

            return result

        if node == "root" or node is None:
            root: dict[str, Any] = {
                "id": "root/root",
                "text": "root",
                "leaf": False,
                "checked": False,
                "expanded": False,
                "children": _build_children("root", 0, is_root=True),
            }
            return [root]

        # Return children of a specific node (lazy load)
        target_path = node.rstrip("/")
        if target_path.startswith("root/"):
            db_prefix = target_path[5:]
        else:
            db_prefix = target_path
        children = _build_children(target_path, len(db_prefix.rstrip("/").split("/")), db_prefix=db_prefix)

        if sorters:
            for s in reversed(sorters):
                prop = s.get("property", "text")
                direction = s.get("direction", "ASC")
                reverse = direction == "DESC"
                if prop == "text":
                    children = sorted(children, key=lambda c: c["text"], reverse=reverse)

        return children
