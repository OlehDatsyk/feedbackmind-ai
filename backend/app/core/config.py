"""Application settings, loaded from environment variables (and an optional local .env file)."""

from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("feedbackmind.config")

AIProviderName = Literal["none", "openai", "anthropic", "gemini"]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-5-5",
    # OpenAI / Gemini model names change often - set AI_MODEL explicitly for these providers.
    "openai": "gpt-4.1",
    "gemini": "gemini-2.5-pro",
    "none": "",
}

_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Real environment variables always win; .env files are a local-development convenience.
    model_config = SettingsConfigDict(
        env_file=(_BACKEND_DIR.parent / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "FeedbackMind AI"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    secret_key: str = Field(default="", description="JWT signing key (min 32 chars). Required in production.")
    database_url: str = "postgresql+psycopg://feedbackmind:feedbackmind@127.0.0.1:5436/feedbackmind"
    db_pool_size: int = 5
    db_max_overflow: int = 5

    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14
    registration_enabled: bool = True
    invitation_expire_days: int = 7

    # AI
    ai_provider: AIProviderName = "none"
    ai_model: str = ""
    ai_effort: Literal["low", "medium", "high"] = "medium"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    ai_timeout_seconds: float = 120.0
    ai_max_retries: int = 2
    ai_batch_size: int = 20
    ai_max_records_per_run: int = 500
    ai_daily_token_limit: int = 2_000_000  # per workspace, 0 = unlimited
    allow_workspace_ai_keys: bool = True
    encryption_key: str = Field(default="", description="Fernet key used to encrypt stored credentials.")

    # Imports
    max_import_mb: int = 20
    max_import_rows: int = 100_000

    # Background jobs
    embedded_worker: bool = True  # run the job worker inside the API process (single-service deployments)
    worker_poll_seconds: float = 2.0
    worker_concurrency: int = 1
    job_lease_seconds: int = 900
    alert_eval_interval_minutes: int = 30

    # Analytics safeguards
    min_sample_size: int = 5  # minimum records before a topic / bucket is treated as more than anecdotal
    min_trend_sample_size: int = 20

    # Rate limiting (per client IP, in-memory, per process)
    rate_limit_auth_per_minute: int = 10
    rate_limit_ai_per_minute: int = 20
    rate_limit_ingest_per_minute: int = 120

    docs_enabled: bool = True
    trusted_proxy_headers: bool = False

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, value: str) -> str:
        # Render / Heroku style URLs -> SQLAlchemy psycopg3 driver.
        if value.startswith("postgres://"):
            value = "postgresql+psycopg://" + value[len("postgres://") :]
        elif value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    @model_validator(mode="after")
    def _check_production(self) -> Settings:
        if self.environment == "production":
            if len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be set to at least 32 random characters in production.")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not supported in production; set DATABASE_URL to PostgreSQL.")
            if "*" in self.cors_origin_list:
                raise ValueError("Wildcard CORS origins are not allowed in production.")
        elif not self.secret_key:
            # Development convenience only: tokens become invalid on restart.
            self.secret_key = secrets.token_urlsafe(48)
            logger.warning("SECRET_KEY not set - generated an ephemeral development key.")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_import_bytes(self) -> int:
        return self.max_import_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def env_api_key(self, provider: str) -> str:
        return {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "gemini": self.gemini_api_key,
        }.get(provider, "")


@lru_cache
def get_settings() -> Settings:
    # The test suite sets FEEDBACKMIND_IGNORE_ENV_FILE so a developer's local .env never leaks into tests.
    if os.environ.get("FEEDBACKMIND_IGNORE_ENV_FILE"):
        return Settings(_env_file=None)  # type: ignore[call-arg]
    return Settings()
