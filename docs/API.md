# FeedbackMind AI - API overview

Interactive documentation (Swagger UI) is served at **`/api/docs`** and the OpenAPI schema at **`/api/openapi.json`** (controlled by `DOCS_ENABLED`). This page summarises conventions and the main endpoints.

## Conventions

- Base path: `/api/v1`. JSON request and response bodies; UTF-8.
- Authentication: `Authorization: Bearer <access_token>` from `/auth/login` or `/auth/register`. Refresh with `/auth/refresh` (the refresh token rotates every time).
- Workspace scope: send `X-Workspace-ID: <uuid>` on workspace-scoped routes. If you belong to exactly one workspace it may be omitted.
- Errors: `{"detail": "human-readable message"}` with standard status codes - 400 bad input, 401 not authenticated, 403 role not allowed, 404 not found (also for other workspaces' IDs), 409 conflict (duplicates, wrong state), 413 too large, 422 validation, 429 rate limited.
- Dates: ISO 8601. Filter dates (`date_from`, `date_to`) are inclusive calendar dates in the workspace time zone.
- Common filter query parameters (feedback list, analytics, topics, trends): `date_from`, `date_to`, `source_id` (repeatable), `product_id`, `topic_id`, `tag_id`, `sentiment` (`positive|negative|neutral|mixed|uncertain|unanalyzed`), `q`, `needs_review`, `include_archived`, `archived_only`, `segment`, `language`, `method` (`lexicon|ai|manual`), `is_demo`.

## Endpoints

| Area | Endpoints |
| --- | --- |
| Health | `GET /health`, `GET /health/ready` (checks the database and migrations) |
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET/PATCH /auth/me`, `POST /auth/change-password` |
| Workspaces | `GET/POST /workspaces`, `GET/PATCH /workspace`, `POST /workspace/delete`, `GET /workspace/activity` |
| Members | `GET /workspace/members`, `PATCH/DELETE /workspace/members/{id}`, `GET/POST /workspace/invitations`, `DELETE /workspace/invitations/{id}`, `GET /invitations/{token}`, `POST /invitations/accept` |
| AI settings | `GET/PUT /workspace/ai-settings` |
| Demo data | `GET/POST/DELETE /workspace/demo` |
| Catalogue | `GET/POST /products`, `PATCH/DELETE /products/{id}`, `GET/POST /sources`, `DELETE /sources/{id}`, `GET/POST /tags`, `DELETE /tags/{id}` |
| Feedback | `GET/POST /feedback`, `GET/PATCH/DELETE /feedback/{id}`, `POST /feedback/bulk`, `POST/DELETE /feedback/{id}/notes`, `PUT /feedback/{id}/tags`, `POST/DELETE /feedback/{id}/topics`, `POST /feedback/{id}/sentiment` (manual correction) |
| Imports | `GET /imports/fields`, `GET/POST /imports` (multipart `file`, optional `encoding`), `GET /imports/{id}`, `POST /imports/{id}/validate`, `POST /imports/{id}/confirm`, `POST /imports/{id}/cancel`, `GET /imports/{id}/errors`, `GET /imports/{id}/errors.csv` |
| Topics | `GET/POST /topics`, `GET/PATCH/DELETE /topics/{id}`, `POST /topics/merge`, `POST /topics/reapply-rules`, `GET /topics/suggestions` |
| Analysis | `GET /analysis/status`, `POST /analysis/run`, `GET /jobs/{id}` |
| Analytics & trends | `GET /analytics/overview`, `GET /analytics/timeseries`, `GET /analytics/breakdown`, `GET /trends` |
| Insights | `GET /insights`, `POST /insights/generate`, `GET/PATCH /insights/{id}` |
| Alerts | `GET /alerts/types`, `GET/POST /alerts/rules`, `PATCH/DELETE /alerts/rules/{id}`, `POST /alerts/evaluate`, `GET /alerts/events`, `PATCH /alerts/events/{id}`, `POST /alerts/events/read-all` |
| Comparisons | `POST /comparisons` |
| AI Analyst | `POST /assistant/ask`, `GET /assistant/conversations`, `GET/DELETE /assistant/conversations/{id}` |
| Reports | `GET/POST /reports`, `GET/DELETE /reports/{id}`, `GET /reports/{id}/download` |
| Integrations | `GET/POST /integrations`, `PATCH/DELETE /integrations/{id}`, `POST /integrations/{id}/rotate` |
| Ingestion | `POST /ingest/feedback` (`X-API-Key`), `POST /ingest/webhooks/{integration_id}` (signed) |

## Example: import a CSV

```bash
curl -X POST "$API/api/v1/imports" -H "Authorization: Bearer $TOKEN" -H "X-Workspace-ID: $WS" -F "file=@sample-data/sample-feedback.csv"
```

```bash
curl -X POST "$API/api/v1/imports/$IMPORT_ID/validate" -H "Authorization: Bearer $TOKEN" -H "X-Workspace-ID: $WS" -H "Content-Type: application/json" -d '{"mapping": {"text": "Review", "received_at": "Date", "rating": "Stars", "product": "Product", "source": "Channel"}, "options": {"date_order": "auto"}}'
```

```bash
curl -X POST "$API/api/v1/imports/$IMPORT_ID/confirm" -H "Authorization: Bearer $TOKEN" -H "X-Workspace-ID: $WS"
```

## Example: push feedback with an API key

```bash
curl -X POST "$API/api/v1/ingest/feedback" -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"records": [{"text": "The new dashboard is great", "external_id": "ticket-42", "product": "Web app", "rating": 5}]}'
```

## Example: signed webhook (Python)

```python
import hashlib, hmac, json, time, urllib.request

body = json.dumps({"text": "Agent solved my issue quickly", "external_id": "chat-981"}).encode()
ts = str(int(time.time()))
sig = "sha256=" + hmac.new(SECRET.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
req = urllib.request.Request(WEBHOOK_URL, data=body, method="POST", headers={
    "Content-Type": "application/json", "X-FeedbackMind-Timestamp": ts, "X-FeedbackMind-Signature": sig})
print(urllib.request.urlopen(req).read())
```
