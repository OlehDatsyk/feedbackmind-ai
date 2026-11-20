"""Role-based access control. Enforced on the backend for every workspace-scoped route."""

from __future__ import annotations

ROLE_RANK = {"viewer": 0, "analyst": 1, "admin": 2, "owner": 3}

# permission -> minimum role
PERMISSIONS: dict[str, str] = {
    "workspace:read": "viewer",
    "feedback:read": "viewer",
    "reports:read": "viewer",
    "assistant:use": "viewer",
    "feedback:write": "analyst",
    "feedback:correct": "analyst",
    "imports:manage": "analyst",
    "analysis:run": "analyst",
    "topics:manage": "analyst",
    "insights:manage": "analyst",
    "alerts:manage": "analyst",
    "reports:create": "analyst",
    "feedback:delete": "admin",
    "integrations:manage": "admin",
    "members:manage": "admin",
    "workspace:update": "admin",
    "ai_settings:manage": "admin",
    "demo:manage": "admin",
    "workspace:delete": "owner",
}


def has_permission(role: str, permission: str) -> bool:
    required = PERMISSIONS[permission]
    return ROLE_RANK.get(role, -1) >= ROLE_RANK[required]


def permissions_for(role: str) -> list[str]:
    return sorted(p for p in PERMISSIONS if has_permission(role, p))
