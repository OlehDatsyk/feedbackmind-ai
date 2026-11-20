"""Workspaces, members, invitations, AI provider settings, demo data and the activity log."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.ai.service import describe, resolve_config, tokens_used_today
from app.api.deps import DB, AdminCtx, Ctx, CurrentUser, OwnerCtx, require
from app.api.v1.auth import create_workspace, find_invitation
from app.core.config import get_settings
from app.core.permissions import ROLE_RANK, permissions_for
from app.core.security import EncryptionUnavailableError, encrypt_secret, encryption_available, generate_opaque_token, hash_token
from app.models import ActivityLog, Invitation, Membership, User, Workspace, WorkspaceAISettings
from app.services.activity import log_activity
from app.services.demo import demo_count, load_demo_data, remove_demo_data
from app.services.serialize import iso

router = APIRouter(tags=["workspaces"])
_TZ = available_timezones()


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    industry: str = Field(default="", max_length=120)
    timezone: str = Field(default="UTC", max_length=64)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    industry: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)


class DeleteWorkspaceIn(BaseModel):
    confirm_name: str


class InviteIn(BaseModel):
    email: EmailStr
    role: str = Field(default="viewer", pattern="^(admin|analyst|viewer)$")


class RoleIn(BaseModel):
    role: str = Field(pattern="^(owner|admin|analyst|viewer)$")


class AcceptIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class AISettingsIn(BaseModel):
    provider: str = Field(pattern="^(default|none|openai|anthropic|gemini)$")
    model: str = Field(default="", max_length=120)
    api_key: str | None = Field(default=None, max_length=500, description="Omit to keep the stored key; empty string removes it.")


def _ws_out(ws: Workspace, role: str | None = None) -> dict:
    return {
        "id": str(ws.id),
        "name": ws.name,
        "description": ws.description,
        "industry": ws.industry,
        "timezone": ws.timezone,
        "created_at": iso(ws.created_at),
        "role": role,
        "permissions": permissions_for(role) if role else [],
    }


def _check_tz(tz: str) -> None:
    if tz not in _TZ:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown time zone '{tz}'. Use an IANA name such as Europe/London.")


@router.get("/workspaces")
def list_workspaces(user: CurrentUser, db: DB) -> list[dict]:
    rows = db.execute(select(Membership, Workspace).join(Workspace).where(Membership.user_id == user.id).order_by(Membership.created_at)).all()
    return [_ws_out(ws, m.role) for m, ws in rows]


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
def create(body: WorkspaceIn, user: CurrentUser, db: DB) -> dict:
    _check_tz(body.timezone)
    ws = create_workspace(db, user, body.name.strip(), body.description, body.industry, body.timezone)
    db.commit()
    return _ws_out(ws, "owner")


@router.get("/workspace")
def current(ctx: Ctx) -> dict:
    return _ws_out(ctx.workspace, ctx.role)


@router.patch("/workspace")
def update_ws(body: WorkspaceUpdate, ctx: AdminCtx, db: DB) -> dict:
    ctx.require("workspace:update")
    ws = ctx.workspace
    data = body.model_dump(exclude_none=True)
    if "timezone" in data:
        _check_tz(data["timezone"])
    for k, v in data.items():
        setattr(ws, k, v.strip() if isinstance(v, str) else v)
    log_activity(db, ws.id, ctx.user.id, "workspace.updated", "Workspace settings updated", "workspace", ws.id, {"fields": list(data)})
    db.commit()
    return _ws_out(ws, ctx.role)


@router.post("/workspace/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_ws(body: DeleteWorkspaceIn, ctx: OwnerCtx, db: DB) -> Response:
    if body.confirm_name.strip() != ctx.workspace.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Type the workspace name exactly to confirm deletion.")
    db.delete(ctx.workspace)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ members


@router.get("/workspace/members")
def members(ctx: Ctx, db: DB) -> list[dict]:
    rows = db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.workspace_id == ctx.workspace_id).order_by(Membership.created_at)
    ).all()
    return [
        {
            "id": str(m.id),
            "user_id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "role": m.role,
            "joined_at": iso(m.created_at),
            "is_you": u.id == ctx.user.id,
        }
        for m, u in rows
    ]


def _owner_count(db, ws_id) -> int:
    return int(db.scalar(select(func.count()).select_from(Membership).where(Membership.workspace_id == ws_id, Membership.role == "owner")) or 0)


@router.patch("/workspace/members/{membership_id}")
def change_role(membership_id: uuid.UUID, body: RoleIn, ctx: AdminCtx, db: DB) -> dict:
    m = db.get(Membership, membership_id)
    if m is None or m.workspace_id != ctx.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    # Admins cannot grant or modify owner-level access; only owners can.
    if (body.role == "owner" or m.role == "owner") and ctx.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can change owner roles.")
    if ROLE_RANK[m.role] > ROLE_RANK[ctx.role]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change the role of a member with more access than you.")
    if m.role == "owner" and body.role != "owner" and _owner_count(db, ctx.workspace_id) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A workspace must keep at least one owner.")
    old = m.role
    m.role = body.role
    log_activity(
        db, ctx.workspace_id, ctx.user.id, "member.role_changed", f"Role changed from {old} to {body.role}", "membership", m.id, {"from": old, "to": body.role}
    )
    db.commit()
    return {"id": str(m.id), "role": m.role}


@router.delete("/workspace/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(membership_id: uuid.UUID, ctx: Ctx, db: DB) -> Response:
    m = db.get(Membership, membership_id)
    if m is None or m.workspace_id != ctx.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found.")
    leaving_self = m.user_id == ctx.user.id
    if not leaving_self:
        ctx.require("members:manage")
        if ROLE_RANK[m.role] >= ROLE_RANK[ctx.role] and ctx.role != "owner":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot remove a member with the same or more access.")
    if m.role == "owner" and _owner_count(db, ctx.workspace_id) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The last owner cannot leave or be removed. Transfer ownership first.")
    db.delete(m)
    log_activity(db, ctx.workspace_id, ctx.user.id, "member.removed", "Member left" if leaving_self else "Member removed", "membership", membership_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ invitations


@router.get("/workspace/invitations")
def list_invitations(ctx: AdminCtx, db: DB) -> list[dict]:
    rows = db.scalars(
        select(Invitation)
        .where(Invitation.workspace_id == ctx.workspace_id, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None))
        .order_by(Invitation.created_at.desc())
    )
    return [{"id": str(i.id), "email": i.email, "role": i.role, "expires_at": iso(i.expires_at), "created_at": iso(i.created_at)} for i in rows]


@router.post("/workspace/invitations", status_code=status.HTTP_201_CREATED)
def invite(body: InviteIn, ctx: AdminCtx, db: DB) -> dict:
    email = body.email.lower()
    existing = db.scalar(select(Membership).join(User).where(Membership.workspace_id == ctx.workspace_id, User.email == email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This person is already a member of the workspace.")
    if body.role == "admin" and ctx.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can invite administrators.")
    token = generate_opaque_token()
    inv = Invitation(
        workspace_id=ctx.workspace_id,
        email=email,
        role=body.role,
        token_hash=hash_token(token),
        invited_by_id=ctx.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().invitation_expire_days),
    )
    db.add(inv)
    log_activity(db, ctx.workspace_id, ctx.user.id, "member.invited", f"Invited {email} as {body.role}", "invitation", None)
    db.commit()
    # No e-mail service is configured: the link is returned once so the admin can share it securely.
    link = f"{get_settings().frontend_url.rstrip('/')}/invite/{token}"
    return {"id": str(inv.id), "email": email, "role": body.role, "expires_at": iso(inv.expires_at), "invite_link": link, "token": token}


@router.delete("/workspace/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(invitation_id: uuid.UUID, ctx: AdminCtx, db: DB) -> Response:
    inv = db.get(Invitation, invitation_id)
    if inv is None or inv.workspace_id != ctx.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
    inv.revoked_at = datetime.now(UTC)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invitations/{token}")
def preview_invitation(token: str, db: DB) -> dict:
    inv = find_invitation(db, token)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The invitation is invalid or has expired.")
    ws = db.get(Workspace, inv.workspace_id)
    return {"workspace_name": ws.name if ws else "", "email": inv.email, "role": inv.role}


@router.post("/invitations/accept")
def accept_invitation(body: AcceptIn, user: CurrentUser, db: DB) -> dict:
    inv = find_invitation(db, body.token)
    if inv is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The invitation is invalid or has expired.")
    if inv.email.lower() != user.email.lower():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This invitation was issued for a different email address.")
    if db.scalar(select(Membership).where(Membership.workspace_id == inv.workspace_id, Membership.user_id == user.id)) is None:
        db.add(Membership(workspace_id=inv.workspace_id, user_id=user.id, role=inv.role))
    inv.accepted_at = datetime.now(UTC)
    log_activity(db, inv.workspace_id, user.id, "member.joined", f"{user.full_name} joined via invitation", "user", user.id)
    db.commit()
    return {"workspace_id": str(inv.workspace_id), "role": inv.role}


# ------------------------------------------------------------------ AI provider settings


@router.get("/workspace/ai-settings")
def get_ai_settings(ctx: Ctx, db: DB) -> dict:
    row = db.scalar(select(WorkspaceAISettings).where(WorkspaceAISettings.workspace_id == ctx.workspace_id))
    settings = get_settings()
    return {
        "workspace_provider": row.provider if row else "default",
        "workspace_model": row.model if row else "",
        "workspace_key_set": bool(row and row.encrypted_api_key),
        "server_provider": settings.ai_provider,
        "effective": describe(resolve_config(db, ctx.workspace_id)),
        "encryption_available": encryption_available(),
        "workspace_keys_allowed": settings.allow_workspace_ai_keys,
        "daily_token_limit": settings.ai_daily_token_limit,
        "tokens_used_24h": tokens_used_today(db, ctx.workspace_id),
        "can_manage": ctx.can("ai_settings:manage"),
    }


@router.put("/workspace/ai-settings", dependencies=[Depends(require("ai_settings:manage"))])
def put_ai_settings(body: AISettingsIn, ctx: Ctx, db: DB) -> dict:
    row = db.scalar(select(WorkspaceAISettings).where(WorkspaceAISettings.workspace_id == ctx.workspace_id))
    if row is None:
        row = WorkspaceAISettings(workspace_id=ctx.workspace_id)
        db.add(row)
    row.provider = body.provider
    row.model = body.model.strip()
    row.updated_by_id = ctx.user.id
    if body.api_key is not None:
        if body.api_key == "":
            row.encrypted_api_key = None
        else:
            if not get_settings().allow_workspace_ai_keys:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Workspace-supplied API keys are disabled on this server.")
            try:
                row.encrypted_api_key = encrypt_secret(body.api_key.strip())
            except EncryptionUnavailableError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{exc} API keys cannot be stored without it.") from exc
    log_activity(db, ctx.workspace_id, ctx.user.id, "ai.settings_updated", f"AI provider set to {body.provider}", "workspace", ctx.workspace_id)
    db.commit()
    return get_ai_settings(ctx, db)


# ------------------------------------------------------------------ demo data


@router.get("/workspace/demo")
def demo_status(ctx: Ctx, db: DB) -> dict:
    return {"demo_records": demo_count(db, ctx.workspace_id)}


@router.post("/workspace/demo", dependencies=[Depends(require("demo:manage"))])
def demo_load(ctx: Ctx, db: DB) -> dict:
    if demo_count(db, ctx.workspace_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Demo data is already loaded.")
    n = load_demo_data(db, ctx.workspace_id, ctx.user.id)
    log_activity(db, ctx.workspace_id, ctx.user.id, "demo.loaded", f"Loaded {n} synthetic demo records", "workspace", ctx.workspace_id)
    db.commit()
    return {"demo_records": n}


@router.delete("/workspace/demo", dependencies=[Depends(require("demo:manage"))])
def demo_remove(ctx: Ctx, db: DB) -> dict:
    n = remove_demo_data(db, ctx.workspace_id)
    log_activity(db, ctx.workspace_id, ctx.user.id, "demo.removed", f"Removed {n} demo records", "workspace", ctx.workspace_id)
    db.commit()
    return {"removed": n}


# ------------------------------------------------------------------ activity


@router.get("/workspace/activity")
def activity(ctx: Ctx, db: DB, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> list[dict]:
    rows = db.execute(
        select(ActivityLog, User.full_name)
        .outerjoin(User, User.id == ActivityLog.user_id)
        .where(ActivityLog.workspace_id == ctx.workspace_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        {
            "id": str(a.id),
            "action": a.action,
            "summary": a.summary,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "user": name,
            "created_at": iso(a.created_at),
        }
        for a, name in rows
    ]
