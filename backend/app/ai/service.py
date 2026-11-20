"""Resolve the effective AI configuration for a workspace, enforce budgets and record usage."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.base import AIConfig, AIError, AINotConfiguredError, AIResult, T, run_structured
from app.ai.providers import get_adapter
from app.core.config import DEFAULT_MODELS, get_settings
from app.core.security import EncryptionUnavailableError, decrypt_secret
from app.db.base import utcnow
from app.models import AIUsage, WorkspaceAISettings

NOT_CONFIGURED_MESSAGE = (
    "AI is not configured, so AI-powered features are unavailable. Data management and statistical analytics still work. "
    "A workspace admin can add a provider in Settings → AI provider, or the server operator can set AI_PROVIDER and an API key."
)


class AIBudgetExceededError(AIError):
    pass


def resolve_config(db: Session, workspace_id: uuid.UUID) -> AIConfig:
    settings = get_settings()
    row = db.scalar(select(WorkspaceAISettings).where(WorkspaceAISettings.workspace_id == workspace_id))
    if row is not None and row.provider != "default":
        provider = row.provider
        model = row.model or DEFAULT_MODELS.get(provider, "")
        key = ""
        if row.encrypted_api_key and settings.allow_workspace_ai_keys:
            try:
                key = decrypt_secret(row.encrypted_api_key)
            except EncryptionUnavailableError:
                key = ""
        if not key and provider in {"openai", "anthropic", "gemini"}:
            key = settings.env_api_key(provider)
        source = "workspace"
    else:
        provider = settings.ai_provider
        model = settings.ai_model or DEFAULT_MODELS.get(provider, "")
        key = settings.env_api_key(provider)
        source = "environment"
    return AIConfig(
        provider=provider,
        model=model,
        api_key=key,
        source=source,
        timeout=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
        effort=settings.ai_effort,
    )


def tokens_used_today(db: Session, workspace_id: uuid.UUID) -> int:
    since = utcnow() - timedelta(hours=24)
    total = db.scalar(
        select(func.coalesce(func.sum(func.coalesce(AIUsage.input_tokens, 0) + func.coalesce(AIUsage.output_tokens, 0)), 0)).where(
            AIUsage.workspace_id == workspace_id, AIUsage.created_at >= since
        )
    )
    return int(total or 0)


def require_ai(db: Session, workspace_id: uuid.UUID) -> AIConfig:
    config = resolve_config(db, workspace_id)
    if not config.is_configured:
        raise AINotConfiguredError(NOT_CONFIGURED_MESSAGE)
    limit = get_settings().ai_daily_token_limit
    if limit and tokens_used_today(db, workspace_id) >= limit:
        raise AIBudgetExceededError("This workspace has reached its 24-hour AI token budget (AI_DAILY_TOKEN_LIMIT). Try again later.")
    return config


def _record_usage(db: Session, workspace_id: uuid.UUID, feature: str, config: AIConfig, result: AIResult | None, error: str | None) -> None:
    # Recorded in the caller's session; every caller commits on both success and handled AI errors.
    db.add(
        AIUsage(
            workspace_id=workspace_id,
            feature=feature,
            provider=config.provider,
            model=config.model,
            input_tokens=result.input_tokens if result else None,
            output_tokens=result.output_tokens if result else None,
            success=error is None,
            error=error[:500] if error else None,
        )
    )


def call_structured(
    db: Session, workspace_id: uuid.UUID, feature: str, system: str, user: str, schema: type[T], max_tokens: int = 16000, config: AIConfig | None = None
) -> AIResult[T]:
    config = config or require_ai(db, workspace_id)
    try:
        result = run_structured(get_adapter(config), config, system, user, schema, max_tokens)
    except AIError as exc:
        _record_usage(db, workspace_id, feature, config, None, str(exc))
        raise
    _record_usage(db, workspace_id, feature, config, result, None)
    return result


def describe(config: AIConfig) -> dict:
    return {
        "provider": config.provider,
        "model": config.model,
        "source": config.source,
        "configured": config.is_configured,
        "api_key_set": bool(config.api_key),
        "message": None if config.is_configured else NOT_CONFIGURED_MESSAGE,
    }
