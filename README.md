# FeedbackMind AI

**Customer feedback intelligence: turn reviews, surveys and support comments into evidence-backed business insights.**

FeedbackMind AI is a multi-tenant SaaS application that collects customer feedback from files, manual entry and integrations, analyses sentiment, topics and emotions, detects trends and emerging problems, and answers business questions - always showing which records, date range and sample size a figure is based on.

> **Honesty by design.** Every figure is computed from stored records. Statistical estimates, observed history and AI-generated interpretations are labelled separately. Without an AI provider the app still works (rule-based analysis, statistics, imports, reports) and says clearly that AI is unavailable. Nothing is invented: no fake integrations, no fake AI output, no hard-coded statistics.

- **Live demo:** https://feedbackmind-ai-frontend.onrender.com (API: https://feedbackmind-ai-api.onrender.com/api/docs) - temporary demo storage: data is erased whenever the free server restarts; use synthetic data only
- **API docs:** `/api/docs` on the backend (OpenAPI / Swagger UI)

---

## Contents

1. [Main features](#main-features)
2. [Technology stack](#technology-stack)
3. [Architecture](#architecture)
4. [AI analysis](#ai-analysis)
5. [Imports](#supported-import-formats)
6. [Analytics and reporting](#analytics-and-reporting)
7. [Screenshots](#screenshots)
8. [Installation and local development](#installation-and-local-development)
9. [Environment variables](#environment-variables)
10. [Database](#database)
11. [AI provider configuration](#ai-provider-configuration)
12. [Running tests](#running-tests)
13. [Deployment](#deployment)
14. [API](#api)
15. [Project structure](#project-structure)
16. [Security](#security)
17. [Known limitations](#known-limitations)
18. [Licence](#licence)

## Main features

| Area | What it does |
| --- | --- |
| **Workspaces & roles** | Fully isolated workspaces; members with Owner / Administrator / Analyst / Viewer roles enforced on the backend; invitations; workspace switching |
| **Overview dashboard** | Volume, sentiment percentages (of classified records), average sentiment, satisfaction over time, topics, sources, products, emotions, newly detected issues, alerts, latest insights, activity - all driven by the same global filters |
| **Feedback Hub** | Add, edit, archive, delete, search (text, title, customer ref, tags), filter (date, sentiment, source, product, topic, review flag), notes, tags, review flags, bulk actions, manual sentiment corrections with full history |
| **Guided import** | CSV / XLSX / JSON: upload → inspect columns → map fields → preview → validate → confirm → background processing; duplicate detection, date parsing with ambiguity detection, rejected-row report |
| **Integrations** | REST API ingestion (API keys), HMAC-signed webhooks; Shopify, Trustpilot, Google Business Profile, Zendesk and Intercom are catalogued with their requirements but **not** simulated |
| **Sentiment & aspects** | Positive / negative / neutral / mixed / uncertain, score, model confidence, explanation, verified text evidence; aspect-level (per-topic) sentiment |
| **Topics** | 12 default topics with editable keyword rules, custom topics, rename, merge, approve AI-proposed topics, manual assignment, TF-IDF topic suggestions |
| **Emotions** | Frustration, satisfaction, confusion, disappointment, appreciation, urgency, concern, excitement - as wording cues, never as a diagnosis |
| **Insights engine** | Recurring issues, rising negative feedback, product hotspots, positive drivers, emerging themes - each with evidence records, supporting count, period, trend, importance, evidence strength and suggested action |
| **Trends** | Daily / weekly / monthly series, OLS trend with p-value, period-over-period z-tests per topic, splits by topic / product / source, minimum sample-size safeguards |
| **AI Business Analyst** | Chat over your workspace's data: deterministic fact pack + retrieved records, citations validated against the records provided, date range and sample size always shown |
| **Smart alerts** | Negative spikes, negative share, sentiment drop, volume spikes, new recurring topics, product complaints, unresolved review items; thresholds, windows, minimum counts, cooldowns |
| **Comparisons** | Two date ranges, products, sources or customer segments with z-tests, improving / declining / emerging topics and explicit warnings |
| **Reports** | PDF, DOCX, XLSX and CSV generated in the background from real records; AI content labelled; formula-injection-safe exports |

## Technology stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL (psycopg 3), PyJWT, Argon2id
- **Data & NLP:** VADER lexicon (rule-based sentiment), langdetect, scikit-learn (TF-IDF), SciPy (regression), openpyxl, charset-normalizer, python-dateutil
- **AI:** provider-independent layer with adapters for Anthropic (official SDK), OpenAI and Google Gemini (REST); structured JSON output validated with Pydantic
- **Reports:** ReportLab (PDF), python-docx (DOCX), openpyxl (XLSX)
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS 4, Radix UI primitives (shadcn-style components), Lucide icons, Recharts, React Router, TanStack Query, React Hook Form, Zod
- **Infrastructure:** Docker Compose (PostgreSQL), Render Blueprint, GitHub Actions CI

## Architecture

```
React SPA (Vite)  ──HTTPS/JSON──▶  FastAPI  /api/v1  ──SQLAlchemy──▶  PostgreSQL
 TanStack Query                     │  auth (JWT + rotating refresh tokens)      ▲
 X-Workspace-ID header              │  RBAC + workspace isolation                │
                                    │  services: imports, analytics, insights,   │
                                    │  alerts, comparisons, reports, assistant   │
                                    ▼                                            │
                       Durable job queue (jobs table) ◀──── worker ──────────────┘
                       imports · AI batches · reports · alert evaluation
                                    │
                                    ▼
                       AI provider adapters (Anthropic / OpenAI / Gemini) - optional
```

- **Workspace isolation:** every workspace-scoped request carries `X-Workspace-ID`; membership is checked on each request and every query filters by the workspace. IDs from other workspaces return 404.
- **Background processing:** a PostgreSQL-backed job queue with atomic claims and leases (no Redis). The worker runs inside the API (`EMBEDDED_WORKER=true`, default) or as a separate process (`python -m app.worker`). Jobs survive restarts and are retried with backoff.
- **No reliance on local disk:** uploaded files (until processed) and generated reports are stored in PostgreSQL, so ephemeral hosting file systems are fine.
- **One filter definition** is shared by lists, cards, charts, exports and reports, so they always agree.

## AI analysis

| Capability | Without AI (default) | With an AI provider |
| --- | --- | --- |
| Sentiment | VADER lexicon, English only, labelled "Rule-based (not AI)", no confidence score; non-English or very short texts → *uncertain* | Label, score, model-reported confidence, explanation, verified quotes; handles sarcasm, negation, mixed opinions, many languages |
| Topics | Keyword rules (editable) | AI aspects mapped to existing topics; new topics proposed for review |
| Emotions | Keyword cues | AI cues with confidence and quotes |
| Insights | Rule-based facts and suggested actions | Plus an AI-written, labelled summary and action - facts unchanged |
| AI Analyst | Computed summary + relevant records | Written answer with validated citations |

Safeguards: feedback is wrapped in tags and treated as untrusted data (prompt-injection guard); quotes not found verbatim in the text are discarded; record IDs the model invents are ignored or removed; manual corrections always win over later AI runs; batch size, records per run and a per-workspace 24-hour token budget limit cost; token usage is recorded per call.

## Supported import formats

- **CSV** (any delimiter detected among `, ; \t |`; UTF-8, UTF-16, then Windows-1252, or an explicit encoding)
- **XLSX** (first worksheet; read-only, values only - macros, formulas and links are never executed; `.xls`/`.xlsm` rejected)
- **JSON** (array of objects or `{"records": [...]}`)
- **Manual entry**, **REST API**, **signed webhooks**

Validation covers required text, dates (ISO, day-first / month-first with file-wide inference; ambiguous dates are rejected rather than guessed; naive times use the workspace time zone), rating scales, field lengths, malformed rows, duplicates inside the file and against existing data. Every rejected row is stored with its reason and can be downloaded as CSV. Valid rows are inserted in a single transaction.

## Analytics and reporting

Charts: sentiment distribution, sentiment over time, negative share over time, volume over time, topic distribution and topic sentiment comparison, feedback by source and product, emotions, negative-share trends by topic / product / source, period-over-period topic changes.

Statistical methods: shares of classified records; two-proportion z-tests (alpha 0.05) for period and segment comparisons; OLS regression for time trends; minimum sample size (default 5 per bucket/topic) with "small sample" flags. Correlation is never presented as causation.

Reports (PDF / DOCX / XLSX / CSV) contain workspace name, report date, date range, volume, sentiment distribution, main topics, emerging problems, positive highlights, insights with evidence, recommended actions (rule-based vs AI-generated labelled), and methodology & limitations.

## Screenshots

Genuine screenshots of the running application have not been added yet. Placeholders:

- `docs/screenshots/overview.png` - Overview dashboard *(to be added)*
- `docs/screenshots/import-wizard.png` - Guided import *(to be added)*
- `docs/screenshots/ai-analyst.png` - AI Business Analyst *(to be added)*

## Installation and local development

**Requirements:** Python 3.12+, Node.js 20+ (22 recommended), Docker Desktop (for PostgreSQL).

### Windows - one click

Double-click **`Start App.bat`**. It checks the required software, creates `backend/.venv`, installs backend and frontend dependencies, creates `.env` with random secrets (only if missing), starts PostgreSQL in Docker, applies migrations and opens http://localhost:5173. It never deletes files or resets the database.

### macOS - one click

Run **`Start App (Mac).command`** (first time: `chmod +x "Start App (Mac).command"`). Same steps as on Windows.

### Manual setup

```bash
docker compose up -d db
```

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cp .env.example .env
```

Set `SECRET_KEY` and `ENCRYPTION_KEY` in `.env` (see comments in `.env.example`), then:

```bash
cd backend && .venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm ci && npm run dev
```

Open http://localhost:5173, create an account, then import data or click **Load sample dataset** (240 synthetic records, clearly labelled and removable).

## Environment variables

See [`.env.example`](.env.example) for every variable with comments. The most important:

| Variable | Required | Secret | Purpose |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | yes (prod) | PostgreSQL connection string (`postgres://` URLs are normalised) |
| `SECRET_KEY` | yes in production | yes | JWT signing key, ≥ 32 characters |
| `ENCRYPTION_KEY` | recommended | yes | Fernet key for webhook secrets and workspace AI keys |
| `ENVIRONMENT` | no | no | `development` / `production` (production enforces secure settings) |
| `CORS_ORIGINS`, `FRONTEND_URL` | yes in production | no | Allowed frontend origin(s); invitation link base |
| `AI_PROVIDER`, `AI_MODEL`, `*_API_KEY` | no | keys yes | Optional AI provider |
| `EMBEDDED_WORKER` | no | no | Run the job worker inside the API (default `true`) |
| `MAX_IMPORT_MB`, `MAX_IMPORT_ROWS` | no | no | Import limits (20 MB, 100,000 rows) |
| `VITE_API_URL` | frontend build | no | Public backend URL (empty = same origin) |

## Database

PostgreSQL 16 via Docker Compose (`127.0.0.1:5436`, volume `feedbackmind-pgdata`). Schema managed by Alembic (`backend/alembic/versions`). UUID primary keys, foreign keys with explicit cascade rules, indexes on all workspace-scoped query paths. A test verifies that migrations upgrade, downgrade and match the ORM models exactly.

## AI provider configuration

Either set it for the whole server in `.env`:

```
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=...        # never commit
AI_MODEL=                    # empty = claude-opus-5-5
```

or per workspace in **Settings → AI provider** (administrators; keys are encrypted with `ENCRYPTION_KEY` and never returned). OpenAI and Gemini require `AI_MODEL` to be set explicitly. AI analysis runs only when a user starts it (selected records or "analyse unanalysed"), in background batches.

## Running tests

```bash
cd backend && .venv/bin/pytest
```

```bash
cd frontend && npm test && npm run typecheck && npm run lint && npm run build
```

Backend tests run on SQLite by default; set `TEST_DATABASE_URL` to run them on PostgreSQL (CI does both). AI providers are mocked - tests never call paid APIs. See `PROJECT_REVIEW.md` for the latest results.

## Deployment

Render Blueprint: [`render.yaml`](render.yaml) creates the FastAPI service (with embedded worker) and the static frontend. The live deployment currently runs as a **temporary demo** on SQLite (data is erased on restart; a banner says so) because the Render workspace's free PostgreSQL slot is in use; switching to PostgreSQL is a one-variable change described in `INSTRUCTION.md`. Step-by-step instructions, the environment checklist and live URLs are in [`INSTRUCTION.md`](INSTRUCTION.md). Docker images: `backend/Dockerfile`, `frontend/Dockerfile`; `docker compose --profile full up` runs everything locally.

## API

Versioned REST API under `/api/v1` - authentication, workspaces, members, products, sources, feedback, imports, topics, analysis, insights, trends, analytics, assistant, alerts, comparisons, reports, integrations and ingestion. Interactive docs at `/api/docs`, schema at `/api/openapi.json`. Overview and examples: [`docs/API.md`](docs/API.md).

## Project structure

```
backend/
  app/
    api/v1/         REST routers (auth, workspaces, feedback, imports, topics, analytics, intelligence, reports, integrations)
    ai/             provider-independent AI layer, adapters, structured-output schemas
    core/           config, security, permissions, rate limiting
    db/ models/     SQLAlchemy base, session and models
    services/       imports, baseline + AI analysis, analytics, insights, alerts, comparisons, assistant, reports, jobs
    worker.py       standalone background worker
  alembic/          migrations
  tests/            pytest suite (auth, isolation, roles, imports, analytics, AI mocks, reports, integrations)
frontend/
  src/pages/        Overview, Feedback, Imports, Topics, Insights, Trends, AI Analyst, Alerts, Comparisons, Reports, Integrations, Settings
  src/components/   layout, charts, UI primitives
  src/lib/          API client, auth/workspace state, filters, types
docs/API.md         API overview
sample-data/        small synthetic CSV for trying the import wizard
render.yaml  docker-compose.yml  Start App.bat  Start App (Mac).command
```

## Security

Argon2id password hashing, short-lived JWTs with rotating refresh tokens and reuse detection, backend-enforced RBAC, workspace isolation tests, parameterised queries, escaped LIKE searches, React output escaping, strict CORS, security headers, rate limiting, upload size/type checks, macro-free spreadsheet parsing, CSV/XLSX formula-injection protection, encrypted integration secrets, hashed API keys, no secrets in logs, prompt-injection safeguards. Details and reporting process: [`SECURITY.md`](SECURITY.md).

## Known limitations

- The built-in (non-AI) sentiment analyser is English-only and lexicon-based; it misreads sarcasm and domain language. Configure an AI provider for better accuracy.
- External connectors (Shopify, Trustpilot, Google Business Profile, Zendesk, Intercom) are not implemented; use the REST API or webhooks.
- No e-mail service: invitations produce a one-time link to share manually.
- Rate limiting is in-memory per process.
- Analytics aggregate in application memory; designed for up to roughly 100k records per workspace query.
- Live calls to AI providers were not exercised in automated tests (mocked by design).

Full review: [`PROJECT_REVIEW.md`](PROJECT_REVIEW.md).

## Licence

MIT - see [`LICENSE`](LICENSE).
