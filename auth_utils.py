"""Authentication and authorization utilities for repository endpoints.

Provides decorators and helpers used with apifairy's ``@api.authenticate``
and plain Flask routes: ``jwt_required``, ``admin_or_owner``,
``get_current_user_id``, and ``require_admin``.
"""

from flask import g, request
from werkzeug.exceptions import Forbidden, Unauthorized

from services.auth_service import decode_token, get_user_groups

# ---------------------------------------------------------------------------
# Helpers shared by all four public symbols below
# ---------------------------------------------------------------------------


def _decode_from_request() -> dict | None:
    """Return the decoded JWT payload from the current request (or ``None``)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer ") :]
    return decode_token(token)


def _get_admin_group_id() -> int:
    from config import get_config_by_name

    cfg = get_config_by_name("development")
    return getattr(cfg, "ADMIN_GROUP_ID", 1)


# ---------------------------------------------------------------------------
# Public API used by repository.py
# ---------------------------------------------------------------------------


def jwt_required(user):
    """apifairy authenticate dependency — validates the bearer token.

    On success returns ``True`` (or anything truthy).  apifairy then injects
    the *user* object into the route when ``with_user=True`` is set on
    ``@api.authenticate``.  We populate ``g.current_user_id`` here so that
    downstream code can call :func:`get_current_user_id`.
    """
    payload = _decode_from_request()
    if not payload:
        raise Unauthorized("Missing or invalid Authorization header")

    g.current_user_id = int(payload["sub"])
    return True


def require_admin(user):
    """apifairy authenticate dependency — requires the user to be an admin.

    Raises :class:`werkzeug.exceptions.Forbidden` when the decoded token does
    not contain the configured admin group ID.
    """
    payload = _decode_from_request()
    if not payload:
        raise Unauthorized("Missing or invalid Authorization header")

    g.current_user_id = int(payload["sub"])
    groups = payload.get("groups", [])
    if _get_admin_group_id() not in groups:
        raise Forbidden("Admin privileges required")
    return True


def get_current_user_id() -> int | None:
    """Return the current user's ID from ``g`` (set by ``jwt_required``)."""
    return getattr(g, "current_user_id", None)


def admin_or_owner(uid: int, owner_username: str) -> bool:
    """True if *uid* is an admin or matches *owner_username*.

    Args:
        uid: current user ID (from :func:`get_current_user_id`).
        owner_username: username of the resource owner.
    """
    from extensions import db
    from models.user import User  # local to keep this module lightweight

    if not uid:
        return False

    user = db.session.query(User).filter_by(idu=uid).first()
    if not user:
        return False

    groups = get_user_groups(uid)
    if _get_admin_group_id() in groups:
        return True

    return getattr(user, "nick", None) == owner_username
