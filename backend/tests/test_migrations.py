"""Migrations apply cleanly, downgrade cleanly, and match the ORM models (no drift)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from app.db.base import Base

BACKEND = Path(__file__).resolve().parents[1]


def _cfg(conn) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["connection"] = conn
    return cfg


def test_upgrade_downgrade_roundtrip_and_no_drift():
    path = Path(tempfile.mkdtemp()) / "mig.db"
    eng = create_engine(f"sqlite:///{path.as_posix()}")
    with eng.begin() as conn:
        command.upgrade(_cfg(conn), "head")
    tables = set(inspect(eng).get_table_names())
    assert {"users", "workspaces", "feedback_records", "jobs", "import_jobs", "insights", "alert_rules", "reports"} <= tables
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": False}), Base.metadata)
    assert diff == [], f"Models and migrations differ: {diff}"
    with eng.begin() as conn:
        command.downgrade(_cfg(conn), "base")
    assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
    eng.dispose()
