"""Creating and updating feedback records (shared by manual entry, imports, API and webhooks)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FeedbackRecord, FeedbackSource, Product, Tag, Topic
from app.services.analysis import active_topics, apply_baseline
from app.services.textutil import content_hash, normalise_text


def get_or_create_product(db: Session, workspace_id: uuid.UUID, name: str | None) -> Product | None:
    name = normalise_text(name or "")[:200]
    if not name:
        return None
    product = db.scalar(select(Product).where(Product.workspace_id == workspace_id, func.lower(Product.name) == name.lower()))
    if product is None:
        product = Product(workspace_id=workspace_id, name=name)
        db.add(product)
        db.flush()
    return product


def get_or_create_source(db: Session, workspace_id: uuid.UUID, name: str | None, kind: str = "other") -> FeedbackSource | None:
    name = normalise_text(name or "")[:200]
    if not name:
        return None
    source = db.scalar(select(FeedbackSource).where(FeedbackSource.workspace_id == workspace_id, func.lower(FeedbackSource.name) == name.lower()))
    if source is None:
        source = FeedbackSource(workspace_id=workspace_id, name=name, kind=kind)
        db.add(source)
        db.flush()
    return source


def get_or_create_tags(db: Session, workspace_id: uuid.UUID, names: list[str]) -> list[Tag]:
    tags: list[Tag] = []
    for raw in names:
        name = normalise_text(raw)[:80]
        if not name or any(t.name.lower() == name.lower() for t in tags):
            continue
        tag = db.scalar(select(Tag).where(Tag.workspace_id == workspace_id, func.lower(Tag.name) == name.lower()))
        if tag is None:
            tag = Tag(workspace_id=workspace_id, name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags


def owned(db: Session, model, workspace_id: uuid.UUID, obj_id: uuid.UUID | None, label: str):
    """Fetch a workspace-owned row or raise 404 (also for rows that belong to another workspace)."""
    if obj_id is None:
        return None
    obj = db.get(model, obj_id)
    if obj is None or obj.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found.")
    return obj


def find_duplicate(db: Session, workspace_id: uuid.UUID, digest: str, exclude_id: uuid.UUID | None = None) -> FeedbackRecord | None:
    stmt = select(FeedbackRecord).where(FeedbackRecord.workspace_id == workspace_id, FeedbackRecord.content_hash == digest)
    if exclude_id:
        stmt = stmt.where(FeedbackRecord.id != exclude_id)
    return db.scalar(stmt.limit(1))


@dataclass
class NewFeedback:
    text: str
    received_at: datetime
    title: str | None = None
    source: FeedbackSource | None = None
    product: Product | None = None
    customer_ref: str | None = None
    customer_segment: str | None = None
    language: str | None = None
    rating: float | None = None
    rating_max: float | None = None
    external_id: str | None = None
    tags: list[Tag] | None = None
    is_demo: bool = False
    import_job_id: uuid.UUID | None = None
    integration_id: uuid.UUID | None = None


def create_record(
    db: Session,
    workspace_id: uuid.UUID,
    data: NewFeedback,
    user_id: uuid.UUID | None,
    topics: list[Topic] | None = None,
    flush: bool = True,
) -> FeedbackRecord:
    text = data.text.strip()
    record = FeedbackRecord(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        text=text,
        title=(data.title or None),
        source_id=data.source.id if data.source else None,
        product_id=data.product.id if data.product else None,
        customer_ref=data.customer_ref or None,
        customer_segment=data.customer_segment or None,
        received_at=data.received_at,
        language=data.language or None,
        rating=data.rating,
        rating_max=data.rating_max,
        external_id=data.external_id or None,
        content_hash=content_hash(text, data.product.id if data.product else None, data.received_at, data.customer_ref),
        is_demo=data.is_demo,
        import_job_id=data.import_job_id,
        integration_id=data.integration_id,
        created_by_id=user_id,
        processing_status="pending",
    )
    if data.tags:
        record.tags = list(data.tags)
    db.add(record)
    apply_baseline(db, record, topics if topics is not None else active_topics(db, workspace_id), is_new=True)
    if flush:
        db.flush()
    return record


def rehash(record: FeedbackRecord) -> None:
    record.content_hash = content_hash(record.text, record.product_id, record.received_at, record.customer_ref)
