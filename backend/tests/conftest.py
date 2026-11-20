"""Test fixtures: isolated database migrated with Alembic, mocked AI providers, helpers.

No test calls a paid AI API: providers are replaced by ``FakeAdapter``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

_TMP = Path(tempfile.mkdtemp(prefix="feedbackmind-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "FEEDBACKMIND_IGNORE_ENV_FILE": "1",
        # Set TEST_DATABASE_URL to run the suite against PostgreSQL (CI does). The database is wiped between tests.
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "AI_PROVIDER": "none",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
        "GEMINI_API_KEY": "",
        "EMBEDDED_WORKER": "false",
        "MAX_IMPORT_MB": "2",
        "RATE_LIMIT_AUTH_PER_MINUTE": "1000",
        "RATE_LIMIT_AI_PER_MINUTE": "1000",
        "RATE_LIMIT_INGEST_PER_MINUTE": "1000",
        "CORS_ORIGINS": "http://localhost:5173",
        "ALERT_EVAL_INTERVAL_MINUTES": "0",
    }
)

import io  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402

from app.ai.base import RawCompletion  # noqa: E402
from app.ai.providers import register_adapter  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import configure_engine  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "Sup3r-secret-pass"


def _engine():
    from app.core.config import Settings

    url = Settings(_env_file=None).database_url
    if not url.startswith("sqlite"):
        return create_engine(url)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


@pytest.fixture(scope="session")
def engine():
    eng = _engine()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        if eng.dialect.name != "sqlite":
            command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    configure_engine(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_db(engine):
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    limiter.reset()


@pytest.fixture
def client(engine):
    from app.main import app

    with TestClient(app) as c:
        yield c


class Account:
    def __init__(self, client: TestClient, email: str, tokens: dict, workspace_id: str | None = None):
        self.client = client
        self.email = email
        self.tokens = tokens
        self.workspace_id = workspace_id

    @property
    def headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.tokens['access_token']}"}
        if self.workspace_id:
            h["X-Workspace-ID"] = self.workspace_id
        return h

    def _h(self, kw):
        headers = {**self.headers, **kw.pop("headers", {})}
        return headers

    def get(self, url, **kw):
        return self.client.get(url, headers=self._h(kw), **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers=self._h(kw), **kw)

    def patch(self, url, **kw):
        return self.client.patch(url, headers=self._h(kw), **kw)

    def put(self, url, **kw):
        return self.client.put(url, headers=self._h(kw), **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self._h(kw), **kw)


def register(client: TestClient, email: str | None = None, workspace: str = "Acme", **extra) -> Account:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "full_name": "Test User", "workspace_name": workspace, **extra})
    assert r.status_code == 201, r.text
    acct = Account(client, email, r.json())
    me = acct.get("/api/v1/auth/me").json()
    if me["workspaces"]:
        acct.workspace_id = me["workspaces"][0]["id"]
    return acct


@pytest.fixture
def alice(client) -> Account:
    return register(client, "alice@example.com", "Alice Co")


@pytest.fixture
def bob(client) -> Account:
    return register(client, "bob@example.com", "Bob Co")


def add_member(owner: Account, email: str, role: str) -> Account:
    """Invite + register a user into the owner's workspace with the given role."""
    r = owner.post("/api/v1/workspace/invitations", json={"email": email, "role": "analyst" if role == "admin" else role})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    r2 = owner.client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "full_name": role.title(), "invitation_token": token})
    assert r2.status_code == 201, r2.text
    acct = Account(owner.client, email, r2.json(), owner.workspace_id)
    if role == "admin":
        members = owner.get("/api/v1/workspace/members").json()
        mid = next(m["id"] for m in members if m["email"] == email)
        assert owner.patch(f"/api/v1/workspace/members/{mid}", json={"role": "admin"}).status_code == 200
    return acct


def days_ago(n: float) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).isoformat()


def add_feedback(acct: Account, text: str, **fields) -> dict:
    r = acct.post("/api/v1/feedback", json={"text": text, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def run_jobs() -> int:
    from app.services.jobs import run_pending_jobs

    return run_pending_jobs()


def csv_bytes(rows: list[list], header: list[str]) -> bytes:
    import csv

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def xlsx_bytes(rows: list[list], header: list[str]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def import_file(acct: Account, name: str, content: bytes, mapping: dict | None = None, options: dict | None = None, confirm: bool = True) -> dict:
    r = acct.post("/api/v1/imports", files={"file": (name, content, "application/octet-stream")})
    assert r.status_code == 201, r.text
    up = r.json()
    v = acct.post(f"/api/v1/imports/{up['id']}/validate", json={"mapping": mapping or up["mapping"], "options": options or {}})
    assert v.status_code == 200, v.text
    result = {"upload": up, "validation": v.json()}
    if confirm:
        c = acct.post(f"/api/v1/imports/{up['id']}/confirm")
        assert c.status_code == 200, c.text
        run_jobs()
        result["final"] = acct.get(f"/api/v1/imports/{up['id']}").json()
    return result


class FakeAdapter:
    """Mocked AI provider. Records prompts; returns queued responses or a schema-appropriate default."""

    name = "anthropic"

    def __init__(self):
        self.calls: list[dict] = []
        self.queue: list[str] = []

    def complete(self, config, system, user, max_tokens):
        self.calls.append({"system": system, "user": user, "config": config})
        if self.queue:
            return RawCompletion(self.queue.pop(0), 100, 50)
        if "classify customer feedback" in system:
            import re

            ids = re.findall(r'<record id="([0-9a-f-]{36})"', user)
            results = []
            for rid in ids:
                body = user.split(f'<record id="{rid}"', 1)[1].split(">", 1)[1].split("</record>", 1)[0].strip()
                neg = any(w in body.lower() for w in ("late", "broken", "rude", "terrible", "slow"))
                results.append(
                    {
                        "id": rid,
                        "sentiment": "negative" if neg else "positive",
                        "score": -0.7 if neg else 0.6,
                        "confidence": 0.82,
                        "explanation": "Mock classification.",
                        "evidence": [body[:20], "THIS QUOTE IS INVENTED"],
                        "language": "en",
                        "topics": [
                            {
                                "name": "Delivery" if "deliver" in body.lower() or "late" in body.lower() else "Brand new AI topic",
                                "sentiment": "negative" if neg else "positive",
                                "evidence": body[:15],
                            }
                        ],
                        "emotions": [{"emotion": "frustration" if neg else "satisfaction", "confidence": 0.7, "evidence": body[:10]}],
                    }
                )
            data = {"results": results}
        elif "insight" in system:
            import re

            keys = re.findall(r'<insight key="([0-9a-f-]{36})"', user)
            data = {"insights": [{"key": k, "summary": "AI summary.", "suggested_action": "AI action."} for k in keys]}
        else:
            import re

            ids = re.findall(r'<record id="([0-9a-f-]{36})"', user)
            fake = "00000000-0000-0000-0000-000000000000"
            data = {
                "answer": f"Customers mention delivery delays [#{ids[0]}] and something else [#{fake}]." if ids else "No data.",
                "cited_record_ids": ([ids[0]] if ids else []) + [fake],
                "data_sufficient": bool(ids),
                "limitations": "Mock.",
            }
        return RawCompletion(json.dumps(data), 1000, 200)


@pytest.fixture
def fake_ai(monkeypatch):
    from app.ai.providers.anthropic_provider import AnthropicAdapter
    from app.core.config import get_settings

    fake = FakeAdapter()
    register_adapter("anthropic", fake)
    s = get_settings()
    monkeypatch.setattr(s, "ai_provider", "anthropic")
    monkeypatch.setattr(s, "anthropic_api_key", "sk-test-not-real")
    monkeypatch.setattr(s, "ai_model", "claude-opus-5-5")
    yield fake
    register_adapter("anthropic", AnthropicAdapter())
