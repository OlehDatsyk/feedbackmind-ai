"""Authentication / authorisation dependencies shared by all routers.

Workspace-scoped routes read the active workspace from the ``X-Workspace-ID`` header. Membership is checked on
every request, and every query in the services layer filters by ``ctx.workspace_id`` - record IDs from another
workspace therefore resolve to 404, never to data.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import has_permission
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Membership, User, Workspace

bearer = HTTPBearer(auto_error=False)

DB = Annotated[Session, Depends(get_db)]

_UNAUTHORISED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(db: DB, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _UNAUTHORISED
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise _UNAUTHORISED
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except ValueError:
        raise _UNAUTHORISED from None
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.token_version != payload.get("ver"):
        raise _UNAUTHORISED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass
class WorkspaceContext:
    user: User
    membership: Membership
    workspace: Workspace

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.membership.workspace_id

    @property
    def role(self) -> str:
        return self.membership.role

    def can(self, permission: str) -> bool:
        return has_permission(self.role, permission)

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role in this workspace does not allow this action.")


def get_workspace_context(
    db: DB,
    user: CurrentUser,
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
) -> WorkspaceContext:
    if x_workspace_id:
        try:
            ws_id = uuid.UUID(x_workspace_id)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid X-Workspace-ID header.") from None
        membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.workspace_id == ws_id))
        if membership is None:
            # Same response whether the workspace does not exist or the user is not a member.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    else:
        memberships = db.scalars(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)).all()
        if not memberships:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of any workspace. Create one first.")
        if len(memberships) > 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You belong to several workspaces; send the X-Workspace-ID header.")
        membership = memberships[0]
    workspace = db.get(Workspace, membership.workspace_id)
    assert workspace is not None
    return WorkspaceContext(user=user, membership=membership, workspace=workspace)


Ctx = Annotated[WorkspaceContext, Depends(get_workspace_context)]


def require(permission: str) -> Callable[[WorkspaceContext], WorkspaceContext]:
    def _dep(ctx: Ctx) -> WorkspaceContext:
        ctx.require(permission)
        return ctx

    return _dep


def Perm(permission: str):  # noqa: N802 - reads like a type in signatures
    return Annotated[WorkspaceContext, Depends(require(permission))]


# Common permission-checked contexts.
ReadCtx = Annotated[WorkspaceContext, Depends(require("feedback:read"))]
WriteCtx = Annotated[WorkspaceContext, Depends(require("feedback:write"))]
AnalystCtx = WriteCtx
AdminCtx = Annotated[WorkspaceContext, Depends(require("members:manage"))]
OwnerCtx = Annotated[WorkspaceContext, Depends(require("workspace:delete"))]
