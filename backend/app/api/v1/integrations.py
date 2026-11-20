"""Integration settings (admin) and the public ingestion endpoints (API key / signed webhook)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from app.api.deps import DB, ReadCtx, require
from app.core.ratelimit import ingest_rate_limit
from app.core.security import EncryptionUnavailableError, decrypt_secret, encrypt_secret, encryption_available
from app.db.base import utcnow
from app.models import FeedbackRecord, FeedbackSource, IntegrationConfig, Product
from app.services.activity import log_activity
from app.services.analysis import active_topics
from app.services.feedback import NewFeedback, create_record, find_duplicate, get_or_create_product, get_or_create_source, owned
from app.services.integrations import PROVIDER_CATALOG, hash_key, new_api_key, new_webhook_secret, verify_signature
from app.services.serialize import iso
from app.services.textutil import content_hash

router = APIRouter(tags=["integrations"])
Manage = Depends(require("integrations:manage"))


class IntegrationIn(BaseModel):
    provider: str = Field(pattern="^(rest_api|webhook)$")
    name: str = Field(min_length=1, max_length=200)
    default_source_id: uuid.UUID | None = None
    default_product_id: uuid.UUID | None = None


class IntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


def _out(c: IntegrationConfig) -> dict:
    # Never returns the key hash or the encrypted secret.
    return {
        "id": str(c.id),
        "provider": c.provider,
        "name": c.name,
        "status": c.status,
        "key_prefix": c.key_prefix,
        "has_secret": bool(c.encrypted_secret),
        "default_source_id": str(c.default_source_id) if c.default_source_id else None,
        "default_product_id": str(c.default_product_id) if c.default_product_id else None,
        "records_received": c.records_received,
        "last_used_at": iso(c.last_used_at),
        "created_at": iso(c.created_at),
        "endpoint": "/api/v1/ingest/feedback" if c.provider == "rest_api" else f"/api/v1/ingest/webhooks/{c.id}",
    }


@router.get("/integrations")
def catalog(ctx: ReadCtx, db: DB) -> dict:
    configs = db.scalars(select(IntegrationConfig).where(IntegrationConfig.workspace_id == ctx.workspace_id).order_by(IntegrationConfig.created_at))
    return {
        "catalog": PROVIDER_CATALOG,
        "configured": [_out(c) for c in configs],
        "encryption_available": encryption_available(),
        "can_manage": ctx.can("integrations:manage"),
    }


@router.post("/integrations", status_code=status.HTTP_201_CREATED, dependencies=[Manage])
def create_integration(body: IntegrationIn, ctx: ReadCtx, db: DB) -> dict:
    owned(db, FeedbackSource, ctx.workspace_id, body.default_source_id, "Source")
    owned(db, Product, ctx.workspace_id, body.default_product_id, "Product")
    c = IntegrationConfig(
        workspace_id=ctx.workspace_id,
        provider=body.provider,
        name=body.name.strip(),
        default_source_id=body.default_source_id,
        default_product_id=body.default_product_id,
        created_by_id=ctx.user.id,
    )
    secret_out: dict = {}
    if body.provider == "rest_api":
        key, prefix, digest = new_api_key()
        c.key_prefix, c.key_hash = prefix, digest
        secret_out = {"api_key": key}
    else:
        secret = new_webhook_secret()
        try:
            c.encrypted_secret = encrypt_secret(secret)
        except EncryptionUnavailableError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{exc} Webhook secrets cannot be stored without it.") from exc
        secret_out = {"signing_secret": secret}
    if c.default_source_id is None:
        c.default_source_id = get_or_create_source(
            db, ctx.workspace_id, f"{'API' if body.provider == 'rest_api' else 'Webhook'}: {c.name}", "api" if body.provider == "rest_api" else "webhook"
        ).id
    db.add(c)
    db.flush()
    log_activity(db, ctx.workspace_id, ctx.user.id, "integration.created", f"Created {body.provider} integration {c.name}", "integration", c.id)
    db.commit()
    return {**_out(c), **secret_out, "secret_notice": "Copy this secret now. It will not be shown again."}


@router.post("/integrations/{integration_id}/rotate", dependencies=[Manage])
def rotate(integration_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict:
    c = owned(db, IntegrationConfig, ctx.workspace_id, integration_id, "Integration")
    if c.provider == "rest_api":
        key, prefix, digest = new_api_key()
        c.key_prefix, c.key_hash = prefix, digest
        out = {"api_key": key}
    else:
        secret = new_webhook_secret()
        try:
            c.encrypted_secret = encrypt_secret(secret)
        except EncryptionUnavailableError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        out = {"signing_secret": secret}
    log_activity(db, ctx.workspace_id, ctx.user.id, "integration.rotated", f"Rotated credentials for {c.name}", "integration", c.id)
    db.commit()
    return {**_out(c), **out, "secret_notice": "Copy this secret now. It will not be shown again."}


@router.patch("/integrations/{integration_id}", dependencies=[Manage])
def update_integration(integration_id: uuid.UUID, body: IntegrationUpdate, ctx: ReadCtx, db: DB) -> dict:
    c = owned(db, IntegrationConfig, ctx.workspace_id, integration_id, "Integration")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    db.commit()
    return _out(c)


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Manage])
def delete_integration(integration_id: uuid.UUID, ctx: ReadCtx, db: DB) -> Response:
    c = owned(db, IntegrationConfig, ctx.workspace_id, integration_id, "Integration")
    db.delete(c)
    log_activity(db, ctx.workspace_id, ctx.user.id, "integration.deleted", f"Deleted integration {c.name}", "integration", integration_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------------------------ ingestion


class IngestRecord(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    received_at: datetime | None = None
    title: str | None = Field(default=None, max_length=300)
    product: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=200)
    customer_ref: str | None = Field(default=None, max_length=200)
    customer_segment: str | None = Field(default=None, max_length=120)
    rating: float | None = Field(default=None, ge=0, le=100)
    rating_max: float | None = Field(default=None, gt=0, le=100)
    language: str | None = Field(default=None, max_length=16)
    external_id: str | None = Field(default=None, max_length=200)

    @field_validator("received_at")
    @classmethod
    def _tz(cls, v):
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v


class IngestBatch(BaseModel):
    records: list[IngestRecord] = Field(min_length=1, max_length=100)


def _ingest(db, c: IntegrationConfig, records: list[IngestRecord]) -> dict:
    topics = active_topics(db, c.workspace_id)
    created, duplicates, errors = [], [], []
    default_source = db.get(FeedbackSource, c.default_source_id) if c.default_source_id else None
    default_product = db.get(Product, c.default_product_id) if c.default_product_id else None
    now = utcnow()
    for i, r in enumerate(records):
        received = r.received_at or now
        if received > now:
            errors.append({"index": i, "error": "received_at is in the future"})
            continue
        if r.rating is not None and r.rating > (r.rating_max or 5):
            errors.append({"index": i, "error": "rating exceeds rating_max"})
            continue
        product = get_or_create_product(db, c.workspace_id, r.product) if r.product else default_product
        if r.external_id and db.scalar(
            select(FeedbackRecord.id).where(FeedbackRecord.workspace_id == c.workspace_id, FeedbackRecord.external_id == r.external_id)
        ):
            duplicates.append({"index": i, "reason": "external_id already exists"})
            continue
        if find_duplicate(db, c.workspace_id, content_hash(r.text, product.id if product else None, received, r.customer_ref)):
            duplicates.append({"index": i, "reason": "identical record already exists"})
            continue
        rec = create_record(
            db,
            c.workspace_id,
            NewFeedback(
                text=r.text,
                received_at=received,
                title=r.title,
                source=get_or_create_source(db, c.workspace_id, r.source, c.provider.replace("rest_", "")) if r.source else default_source,
                product=product,
                customer_ref=r.customer_ref,
                customer_segment=r.customer_segment,
                rating=r.rating,
                rating_max=(r.rating_max or 5.0) if r.rating is not None else None,
                language=r.language,
                external_id=r.external_id,
                integration_id=c.id,
            ),
            None,
            topics,
        )
        created.append(str(rec.id))
    c.records_received += len(created)
    c.last_used_at = now
    db.commit()
    return {"created": created, "duplicates": duplicates, "errors": errors}


@router.post("/ingest/feedback", status_code=status.HTTP_201_CREATED, dependencies=[Depends(ingest_rate_limit)], tags=["ingestion"])
def ingest_with_key(body: IngestBatch, db: DB, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header.")
    c = db.scalar(select(IntegrationConfig).where(IntegrationConfig.key_hash == hash_key(x_api_key), IntegrationConfig.provider == "rest_api"))
    if c is None or c.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or disabled API key.")
    return _ingest(db, c, body.records)


@router.post("/ingest/webhooks/{integration_id}", dependencies=[Depends(ingest_rate_limit)], tags=["ingestion"])
async def ingest_webhook(
    integration_id: uuid.UUID,
    request: Request,
    db: DB,
    x_signature: str | None = Header(default=None, alias="X-FeedbackMind-Signature"),
    x_timestamp: str | None = Header(default=None, alias="X-FeedbackMind-Timestamp"),
) -> dict:
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Payload too large.")
    c = db.get(IntegrationConfig, integration_id)
    # Same error for unknown, disabled and badly signed requests (no information leak).
    unauthorised = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature.")
    if c is None or c.provider != "webhook" or c.status != "active" or not c.encrypted_secret:
        raise unauthorised
    try:
        secret = decrypt_secret(c.encrypted_secret)
    except EncryptionUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webhook verification is unavailable on this server.") from None
    if verify_signature(secret, x_timestamp, x_signature, body) is not None:
        raise unauthorised
    try:
        payload = json.loads(body)
        records = IngestBatch.model_validate(payload if isinstance(payload, dict) and "records" in payload else {"records": [payload]}).records
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Invalid payload: {str(exc)[:300]}") from None
    return _ingest(db, c, records)
