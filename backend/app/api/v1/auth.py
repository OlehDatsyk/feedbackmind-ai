"""Registration, login, token refresh/rotation, logout, profile and password management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.permissions import permissions_for
from app.core.ratelimit import auth_rate_limit
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.models import Invitation, Membership, RefreshToken, User, Workspace
from app.services.activity import log_activity
from app.services.analysis import ensure_default_topics

router = APIRouter(prefix="/auth", tags=["auth"])

_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password-1")


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    workspace_name: str | None = Field(default=None, max_length=200)
    invitation_token: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - token type label
    expires_in: int


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


def _issue_tokens(db: Session, user: User, family_id: uuid.UUID | None = None) -> TokenOut:
    access, expires_in = create_access_token(user.id, user.token_version)
    refresh = generate_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh),
            family_id=family_id or uuid.uuid4(),
            expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_expire_days),
        )
    )
    return TokenOut(access_token=access, refresh_token=refresh, expires_in=expires_in)


def find_invitation(db: Session, token: str) -> Invitation | None:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    if inv is None or inv.accepted_at or inv.revoked_at:
        return None
    exp = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=UTC)
    if exp < datetime.now(UTC):
        return None
    return inv


def create_workspace(db: Session, user: User, name: str, description: str = "", industry: str = "", timezone: str = "UTC") -> Workspace:
    ws = Workspace(name=name[:200], description=description, industry=industry, timezone=timezone, created_by_id=user.id)
    db.add(ws)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=ws.id, role="owner"))
    ensure_default_topics(db, ws.id)
    log_activity(db, ws.id, user.id, "workspace.created", f"Workspace '{ws.name}' created", "workspace", ws.id)
    return ws


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(auth_rate_limit)])
def register(body: RegisterIn, db: DB) -> TokenOut:
    email = body.email.lower()
    if (err := validate_password_strength(body.password)) is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, err)
    invitation = None
    if body.invitation_token:
        invitation = find_invitation(db, body.invitation_token)
        if invitation is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The invitation is invalid or has expired.")
        if invitation.email.lower() != email:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This invitation was issued for a different email address.")
    elif not get_settings().registration_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Public registration is disabled. Ask an administrator for an invitation.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    user = User(email=email, full_name=body.full_name.strip(), password_hash=hash_password(body.password), last_login_at=datetime.now(UTC))
    db.add(user)
    db.flush()
    if invitation is not None:
        db.add(Membership(user_id=user.id, workspace_id=invitation.workspace_id, role=invitation.role))
        invitation.accepted_at = datetime.now(UTC)
        log_activity(db, invitation.workspace_id, user.id, "member.joined", f"{user.full_name} joined via invitation", "user", user.id)
    else:
        create_workspace(db, user, (body.workspace_name or "").strip() or f"{user.full_name}'s workspace")
    tokens = _issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/login", response_model=TokenOut, dependencies=[Depends(auth_rate_limit)])
def login(body: LoginIn, db: DB) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    if not verify_password(body.password, user.password_hash) or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = datetime.now(UTC)
    tokens = _issue_tokens(db, user)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(auth_rate_limit)])
def refresh(body: RefreshIn, db: DB) -> TokenOut:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)))
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")
    if token is None:
        raise invalid
    now = datetime.now(UTC)
    if token.revoked_at is not None or token.rotated_at is not None:
        db.execute(update(RefreshToken).where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=now))
        db.commit()
        raise invalid
    exp = token.expires_at if token.expires_at.tzinfo else token.expires_at.replace(tzinfo=UTC)
    if exp < now:
        raise invalid
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise invalid
    token.rotated_at = now
    tokens = _issue_tokens(db, user, family_id=token.family_id)
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshIn, db: DB) -> Response:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)))
    if token is not None:
        db.execute(
            update(RefreshToken).where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC))
        )
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(user: CurrentUser, db: DB) -> dict:
    rows = db.execute(
        select(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
    ).all()
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "workspaces": [{"id": str(ws.id), "name": ws.name, "role": m.role, "timezone": ws.timezone, "permissions": permissions_for(m.role)} for m, ws in rows],
    }


@router.patch("/me")
def update_profile(body: ProfileIn, user: CurrentUser, db: DB) -> dict:
    user.full_name = body.full_name.strip()
    db.commit()
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name}


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(auth_rate_limit)])
def change_password(body: PasswordChangeIn, user: CurrentUser, db: DB) -> Response:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect.")
    if (err := validate_password_strength(body.new_password)) is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, err)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # invalidates existing access tokens
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    log_activity(db, None, user.id, "user.password_changed", "Password changed")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
