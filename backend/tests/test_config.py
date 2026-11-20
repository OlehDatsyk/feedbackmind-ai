"""Production settings checks, including the opt-in temporary demo mode."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

SECRET = "x" * 40


def _prod(**overrides) -> Settings:
    values = {
        "environment": "production",
        "secret_key": SECRET,
        "cors_origins": "https://app.example.com",
        "database_url": "postgresql://u:p@db:5432/fm",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_production_postgres_is_persistent():
    s = _prod()
    assert s.database_url.startswith("postgresql+psycopg://")
    assert s.storage_mode == "persistent"


def test_production_rejects_sqlite_without_demo_flag():
    with pytest.raises(ValidationError, match="SQLite is not supported in production"):
        _prod(database_url="sqlite:///./demo.db")


def test_production_allows_sqlite_only_as_flagged_temporary_demo():
    s = _prod(database_url="sqlite:///./demo.db", ephemeral_demo=True)
    assert s.storage_mode == "temporary"


def test_demo_flag_with_postgres_stays_persistent():
    assert _prod(ephemeral_demo=True).storage_mode == "persistent"


def test_production_still_requires_secret_and_no_wildcard_cors():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _prod(secret_key="short", database_url="sqlite:///./demo.db", ephemeral_demo=True)
    with pytest.raises(ValidationError, match="Wildcard CORS"):
        _prod(cors_origins="*")


def test_health_reports_storage_mode(client):
    assert client.get("/health").json()["storage"] == "persistent"
    assert client.get("/health/ready").json()["storage"] == "persistent"
