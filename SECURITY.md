# Security

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Security → Report a vulnerability** form on this repository rather than in a public issue. Include steps to reproduce and the affected version. Do not include real customer data in reports.

## Security model

| Area | Implementation |
| --- | --- |
| Passwords | Argon2id (argon2-cffi), automatic rehash on login; minimum 10 characters with a letter and a digit; constant-time comparison and a dummy hash for unknown accounts |
| Sessions | HS256 JWT access tokens (15 min) + opaque refresh tokens (SHA-256 hashed at rest, 14 days) rotated on every use; reuse of a rotated token revokes the whole token family; password change revokes all sessions |
| Authorisation | Roles Owner / Administrator / Analyst / Viewer mapped to explicit permissions (`backend/app/core/permissions.py`), checked on the backend for every route; the frontend only hides controls |
| Workspace isolation | `X-Workspace-ID` resolved against the caller's memberships on each request; every query filters by workspace; foreign IDs return 404. Covered by `tests/test_auth_workspaces.py` (ID tampering, header forgery, bulk actions, foreign product references) and AI analyst isolation tests |
| Injection | SQLAlchemy parameterised queries; user search terms are LIKE-escaped; no raw SQL with user input |
| XSS | React escapes all rendered text; no `dangerouslySetInnerHTML`; the AI Analyst uses a minimal Markdown renderer that never emits HTML; API responses carry `Content-Security-Policy: default-src 'none'` |
| CSRF | Not applicable: authentication uses bearer tokens, never cookies; CORS allows only configured origins (wildcards are rejected in production) |
| Headers | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, HSTS in production, `Cache-Control: no-store` on API responses |
| Rate limiting | Sliding-window limits per client IP for authentication, AI and ingestion endpoints (in-memory, per process; put an edge limiter in front for multi-instance deployments) |
| Uploads | Extension allow-list (.csv/.xlsx/.json), Content-Length limit before reading, size limit while reading, row limit, ZIP-bomb guard, `.xls/.xlsm` and workbooks containing `vbaProject.bin` rejected, openpyxl read-only/values-only (no macros, formulas or external links executed), safe filenames, files stored in the database not on disk |
| Exports | CSV/XLSX cells starting with `= + - @ \t \r` are prefixed with `'` (formula-injection protection), including the rejected-rows report |
| Secrets | Webhook signing secrets and workspace AI keys encrypted with Fernet (`ENCRYPTION_KEY`); API keys stored as SHA-256 hashes; secrets shown once and never returned by the API; `AIConfig.__repr__` hides keys; HTTP client loggers are quieted |
| Webhooks | HMAC-SHA256 over `timestamp.body`, constant-time comparison, 5-minute replay window, identical error for unknown/disabled/badly signed integrations |
| Errors | Generic 500 messages; validation errors never echo submitted values |
| AI / prompt injection | Feedback is passed as untrusted data inside tags with explicit instructions not to follow embedded instructions; the AI has no tools and cannot change data; outputs are schema-validated; quotes not present in the source text and record IDs not provided to the model are discarded; per-workspace token budget |
| Audit | Activity log for data changes, corrections, imports, role changes, integration and AI settings changes (no secrets or full feedback text) |

## Secrets handling

- Real `.env` files are git-ignored; `.env.example` contains placeholders only.
- Production refuses to start without a ≥ 32-character `SECRET_KEY`, refuses SQLite and wildcard CORS.
- If a secret is ever committed, deleting it from the latest commit is not enough: rotate it at the provider (and purge it from history if needed).
- Changing `ENCRYPTION_KEY` makes stored webhook secrets and workspace AI keys unreadable; re-enter them after rotation.

## Data protection notes

- Customer personal data is not required: feedback can be anonymous, and the customer reference field is optional.
- Enabling an AI provider sends the feedback text being analysed to that provider. Choose a provider and data-processing terms appropriate for your data.
- Workspace deletion permanently removes all its data (cascade).

## Known limitations

- In-memory rate limiting and a per-process embedded worker are designed for single-instance deployments.
- Multipart uploads without a `Content-Length` header are parsed by the framework (spooled to a temporary file) before the application size check runs.
- No multi-factor authentication or SSO yet.
