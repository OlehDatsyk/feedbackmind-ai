"""Audit / activity log. Never store secrets, passwords or full feedback text in details."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import ActivityLog


def log_activity(
    db: Session,
    workspace_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    action: str,
    summary: str = "",
    entity_type: str | None = None,
    entity_id: uuid.UUID | str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        ActivityLog(
            workspace_id=workspace_id,
            user_id=user_id,
            action=action,
            summary=summary[:500],
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            details=details or {},
        )
    )
