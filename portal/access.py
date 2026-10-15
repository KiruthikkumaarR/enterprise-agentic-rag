"""Access control: which documents a user may see, expressed both as a Python check and as a Qdrant filter.

Roles: executive > manager > employee; admin = employee rights + user management.
    level 1  All staff   -> everyone
    level 2  Department  -> users in one of the document's departments, managers, executives
    level 3  Management  -> managers and executives
    level 4  Executive   -> executives only
"""
from __future__ import annotations

from qdrant_client import models

ROLE_RANK = {"employee": 1, "admin": 1, "manager": 3, "executive": 4}


def max_level(user: dict) -> int:
    return ROLE_RANK.get(user["role"], 1)


def can_see(user: dict, doc: dict) -> bool:
    lvl = int(doc["level"])
    if lvl == 1:
        return True
    if lvl == 2:
        return max_level(user) >= 3 or user["department"] in doc["departments"]
    return max_level(user) >= lvl


def allowed_upload_levels(user: dict) -> list[int]:
    return [l for l in (1, 2, 3, 4) if l <= max(2, max_level(user))]


def can_manage_users(user: dict) -> bool:
    return user["role"] in ("admin", "executive")


def can_delete(user: dict, doc: dict) -> bool:
    return user["role"] in ("admin", "executive") or doc.get("uploaded_by") == user["username"]


def qdrant_filter(user: dict) -> models.Filter | None:
    """Filter evaluated inside Qdrant, so documents a user may not see are never retrieved at all."""
    top = max_level(user)
    if top >= 4:
        return None
    if top >= 3:
        return models.Filter(must=[models.FieldCondition(key="level", range=models.Range(lte=3))])
    return models.Filter(should=[
        models.FieldCondition(key="level", match=models.MatchValue(value=1)),
        models.Filter(must=[models.FieldCondition(key="level", match=models.MatchValue(value=2)),
                            models.FieldCondition(key="departments", match=models.MatchAny(any=[user["department"]]))]),
    ])
