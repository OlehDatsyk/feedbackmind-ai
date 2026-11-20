"""Feedback Hub: CRUD, search/filter, notes, tags, topics, review flags, archive, manual sentiment corrections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select

from app.api.deps import DB, AdminCtx, ReadCtx, WriteCtx
from app.db.base import utcnow
from app.models import SENTIMENT_LABELS, EmotionAnalysis, FeedbackNote, FeedbackRecord, FeedbackSource, FeedbackTopic, Product, SentimentAnalysis, Topic, User
from app.services.activity import log_activity
from app.services.analysis import active_topics, apply_baseline, correct_sentiment
from app.services.feedback import NewFeedback, create_record, find_duplicate, get_or_create_source, get_or_create_tags, owned, rehash
from app.services.filters import FeedbackFilter, apply_filters, filter_params
from app.services.serialize import feedback_summary, iso
from app.services.textutil import content_hash

router = APIRouter(prefix="/feedback", tags=["feedback"])

SORTS = {
    "newest": FeedbackRecord.received_at.desc(),
    "oldest": FeedbackRecord.received_at.asc(),
    "most_negative": FeedbackRecord.sentiment_score.asc(),
    "most_positive": FeedbackRecord.sentiment_score.desc(),
    "rating_low": FeedbackRecord.rating.asc(),
    "rating_high": FeedbackRecord.rating.desc(),
}


class FeedbackIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    title: str | None = Field(default=None, max_length=300)
    source_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    customer_ref: str | None = Field(default=None, max_length=200)
    customer_segment: str | None = Field(default=None, max_length=120)
    received_at: datetime | None = None
    language: str | None = Field(default=None, max_length=16)
    rating: float | None = Field(default=None, ge=0, le=100)
    rating_max: float | None = Field(default=None, gt=0, le=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    allow_duplicate: bool = False

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Feedback text cannot be empty")
        return v

    @field_validator("received_at")
    @classmethod
    def _tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v


class FeedbackUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=20000)
    title: str | None = Field(default=None, max_length=300)
    source_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    customer_ref: str | None = Field(default=None, max_length=200)
    customer_segment: str | None = Field(default=None, max_length=120)
    received_at: datetime | None = None
    language: str | None = Field(default=None, max_length=16)
    rating: float | None = Field(default=None, ge=0, le=100)
    rating_max: float | None = Field(default=None, gt=0, le=100)
    needs_review: bool | None = None
    is_archived: bool | None = None


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class TagsIn(BaseModel):
    tags: list[str] = Field(max_length=30)


class TopicAssignIn(BaseModel):
    topic_id: uuid.UUID
    sentiment: str | None = None


class CorrectionIn(BaseModel):
    label: str
    note: str = Field(default="", max_length=1000)


class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    action: str = Field(pattern="^(archive|unarchive|mark_review|clear_review|add_tag|delete)$")
    tag: str | None = Field(default=None, max_length=80)


def _get(db, ctx, feedback_id: uuid.UUID) -> FeedbackRecord:
    return owned(db, FeedbackRecord, ctx.workspace_id, feedback_id, "Feedback")


@router.get("")
def list_feedback(
    ctx: ReadCtx,
    db: DB,
    f: FeedbackFilter = Depends(filter_params),
    sort: str = Query("newest"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    tz = ctx.workspace.timezone
    total = db.scalar(apply_filters(select(func.count(FeedbackRecord.id)), ctx.workspace_id, f, tz)) or 0
    order = SORTS.get(sort, SORTS["newest"])
    stmt = apply_filters(select(FeedbackRecord), ctx.workspace_id, f, tz).order_by(order.nulls_last(), FeedbackRecord.id).limit(limit).offset(offset)
    items = [feedback_summary(r) for r in db.scalars(stmt).unique()]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_feedback(body: FeedbackIn, ctx: WriteCtx, db: DB) -> dict:
    product = owned(db, Product, ctx.workspace_id, body.product_id, "Product")
    source = (
        owned(db, FeedbackSource, ctx.workspace_id, body.source_id, "Source")
        if body.source_id
        else get_or_create_source(db, ctx.workspace_id, "Manual entry", "manual")
    )
    received = body.received_at or utcnow()
    if received > utcnow() + timedelta(minutes=5):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The received date cannot be in the future.")
    if body.rating is not None and body.rating > (body.rating_max or 5):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Rating is larger than the rating scale.")
    digest = content_hash(body.text, product.id if product else None, received, body.customer_ref)
    dup = find_duplicate(db, ctx.workspace_id, digest)
    if dup is not None and not body.allow_duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"A matching feedback record already exists (id {dup.id}). Set allow_duplicate to save it anyway.")
    rec = create_record(
        db,
        ctx.workspace_id,
        NewFeedback(
            text=body.text,
            received_at=received,
            title=body.title,
            source=source,
            product=product,
            customer_ref=body.customer_ref,
            customer_segment=body.customer_segment,
            language=body.language,
            rating=body.rating,
            rating_max=(body.rating_max or 5.0) if body.rating is not None else None,
            tags=get_or_create_tags(db, ctx.workspace_id, body.tags),
        ),
        ctx.user.id,
    )
    log_activity(db, ctx.workspace_id, ctx.user.id, "feedback.created", "Feedback added manually", "feedback", rec.id)
    db.commit()
    db.refresh(rec)
    return feedback_summary(rec)


@router.get("/{feedback_id}")
def get_feedback(feedback_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict:
    rec = _get(db, ctx, feedback_id)
    analyses = db.execute(
        select(SentimentAnalysis, User.full_name)
        .outerjoin(User, User.id == SentimentAnalysis.created_by_id)
        .where(SentimentAnalysis.feedback_id == rec.id)
        .order_by(SentimentAnalysis.created_at.desc())
    ).all()
    emotions = db.scalars(select(EmotionAnalysis).where(EmotionAnalysis.feedback_id == rec.id).order_by(EmotionAnalysis.created_at.desc())).all()
    notes = db.execute(
        select(FeedbackNote, User.full_name)
        .outerjoin(User, User.id == FeedbackNote.author_id)
        .where(FeedbackNote.feedback_id == rec.id)
        .order_by(FeedbackNote.created_at)
    ).all()
    out = feedback_summary(rec)
    out["topics"] = [
        {"id": str(link.topic_id), "name": link.topic.name, "sentiment": link.sentiment, "assigned_by": link.assigned_by, "evidence": link.evidence}
        for link in sorted(rec.topic_links, key=lambda x: x.topic.name)
    ]
    out["analyses"] = [
        {
            "id": str(a.id),
            "method": a.method,
            "label": a.label,
            "score": a.score,
            "confidence": a.confidence,
            "explanation": a.explanation,
            "evidence": a.evidence,
            "language": a.language,
            "provider": a.provider,
            "model": a.model,
            "previous_label": a.previous_label,
            "corrected_by": name,
            "created_at": iso(a.created_at),
        }
        for a, name in analyses
    ]
    out["emotions"] = [
        {
            "id": str(e.id),
            "method": e.method,
            "emotions": e.emotions,
            "primary_emotion": e.primary_emotion,
            "explanation": e.explanation,
            "model": e.model,
            "created_at": iso(e.created_at),
        }
        for e in emotions
    ]
    out["notes"] = [{"id": str(n.id), "body": n.body, "author": name, "created_at": iso(n.created_at)} for n, name in notes]
    return out


@router.patch("/{feedback_id}")
def update_feedback(feedback_id: uuid.UUID, body: FeedbackUpdate, ctx: WriteCtx, db: DB) -> dict:
    rec = _get(db, ctx, feedback_id)
    data = body.model_dump(exclude_unset=True)
    if "product_id" in data:
        owned(db, Product, ctx.workspace_id, data["product_id"], "Product")
    if "source_id" in data:
        owned(db, FeedbackSource, ctx.workspace_id, data["source_id"], "Source")
    if "received_at" in data and data["received_at"] is not None:
        if data["received_at"].tzinfo is None:
            data["received_at"] = data["received_at"].replace(tzinfo=UTC)
        if data["received_at"] > utcnow() + timedelta(minutes=5):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The received date cannot be in the future.")
    if "received_at" in data and data["received_at"] is None:
        data.pop("received_at")
    text_changed = "text" in data and data["text"] is not None and data["text"].strip() != rec.text
    changed = []
    for k, v in data.items():
        if k == "text" and v is not None:
            v = v.strip()
        if getattr(rec, k) != v:
            setattr(rec, k, v)
            changed.append(k)
    rehash(rec)
    if text_changed:
        # Earlier AI/manual classifications describe the old text: re-run the baseline on the new text.
        # All earlier analyses stay in the history.
        rec.sentiment_method = None
        rec.ai_status = "not_requested"
        db.execute(delete(FeedbackTopic).where(FeedbackTopic.feedback_id == rec.id, FeedbackTopic.assigned_by == "ai"))
        apply_baseline(db, rec, active_topics(db, ctx.workspace_id))
    if changed:
        log_activity(db, ctx.workspace_id, ctx.user.id, "feedback.updated", f"Updated {', '.join(changed)}", "feedback", rec.id, {"fields": changed})
    db.commit()
    db.refresh(rec)
    return feedback_summary(rec)


@router.delete("/{feedback_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback(feedback_id: uuid.UUID, ctx: AdminCtx, db: DB) -> Response:
    ctx.require("feedback:delete")
    rec = _get(db, ctx, feedback_id)
    db.delete(rec)
    log_activity(db, ctx.workspace_id, ctx.user.id, "feedback.deleted", "Feedback record permanently deleted", "feedback", feedback_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/bulk")
def bulk(body: BulkIn, ctx: WriteCtx, db: DB) -> dict:
    if body.action == "delete":
        ctx.require("feedback:delete")
    records = list(db.scalars(select(FeedbackRecord).where(FeedbackRecord.workspace_id == ctx.workspace_id, FeedbackRecord.id.in_(body.ids))).unique())
    tag = None
    if body.action == "add_tag":
        if not body.tag:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "tag is required for add_tag.")
        tag = get_or_create_tags(db, ctx.workspace_id, [body.tag])[0]
    for r in records:
        if body.action == "archive":
            r.is_archived = True
        elif body.action == "unarchive":
            r.is_archived = False
        elif body.action == "mark_review":
            r.needs_review = True
        elif body.action == "clear_review":
            r.needs_review = False
        elif body.action == "add_tag" and tag is not None and tag not in r.tags:
            r.tags.append(tag)
        elif body.action == "delete":
            db.delete(r)
    log_activity(
        db,
        ctx.workspace_id,
        ctx.user.id,
        f"feedback.bulk_{body.action}",
        f"Bulk {body.action} on {len(records)} records",
        "feedback",
        None,
        {"count": len(records)},
    )
    db.commit()
    return {"updated": len(records), "not_found": len(body.ids) - len(records)}


@router.post("/{feedback_id}/notes", status_code=status.HTTP_201_CREATED)
def add_note(feedback_id: uuid.UUID, body: NoteIn, ctx: WriteCtx, db: DB) -> dict:
    rec = _get(db, ctx, feedback_id)
    n = FeedbackNote(workspace_id=ctx.workspace_id, feedback_id=rec.id, author_id=ctx.user.id, body=body.body.strip())
    db.add(n)
    db.commit()
    return {"id": str(n.id), "body": n.body, "author": ctx.user.full_name, "created_at": iso(n.created_at)}


@router.delete("/{feedback_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(feedback_id: uuid.UUID, note_id: uuid.UUID, ctx: WriteCtx, db: DB) -> Response:
    rec = _get(db, ctx, feedback_id)
    n = db.get(FeedbackNote, note_id)
    if n is None or n.feedback_id != rec.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found.")
    if n.author_id != ctx.user.id and not ctx.can("members:manage"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the author or an admin can delete this note.")
    db.delete(n)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{feedback_id}/tags")
def set_tags(feedback_id: uuid.UUID, body: TagsIn, ctx: WriteCtx, db: DB) -> dict:
    rec = _get(db, ctx, feedback_id)
    rec.tags = get_or_create_tags(db, ctx.workspace_id, body.tags)
    db.commit()
    db.refresh(rec)
    return feedback_summary(rec)


@router.post("/{feedback_id}/topics")
def assign_topic(feedback_id: uuid.UUID, body: TopicAssignIn, ctx: WriteCtx, db: DB) -> dict:
    rec = _get(db, ctx, feedback_id)
    topic = owned(db, Topic, ctx.workspace_id, body.topic_id, "Topic")
    if body.sentiment is not None and body.sentiment not in SENTIMENT_LABELS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid sentiment.")
    link = db.get(FeedbackTopic, (rec.id, topic.id))
    if link is None:
        db.add(FeedbackTopic(feedback_id=rec.id, topic_id=topic.id, sentiment=body.sentiment, assigned_by="manual"))
    else:
        link.assigned_by = "manual"
        if body.sentiment is not None:
            link.sentiment = body.sentiment
    log_activity(db, ctx.workspace_id, ctx.user.id, "feedback.topic_assigned", f"Assigned topic {topic.name}", "feedback", rec.id)
    db.commit()
    db.refresh(rec)
    return feedback_summary(rec)


@router.delete("/{feedback_id}/topics/{topic_id}")
def remove_topic(feedback_id: uuid.UUID, topic_id: uuid.UUID, ctx: WriteCtx, db: DB) -> dict:
    rec = _get(db, ctx, feedback_id)
    db.execute(delete(FeedbackTopic).where(FeedbackTopic.feedback_id == rec.id, FeedbackTopic.topic_id == topic_id))
    log_activity(db, ctx.workspace_id, ctx.user.id, "feedback.topic_removed", "Removed topic", "feedback", rec.id, {"topic_id": str(topic_id)})
    db.commit()
    db.refresh(rec)
    return feedback_summary(rec)


@router.post("/{feedback_id}/sentiment")
def correct(feedback_id: uuid.UUID, body: CorrectionIn, ctx: WriteCtx, db: DB) -> dict:
    ctx.require("feedback:correct")
    if body.label not in SENTIMENT_LABELS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"label must be one of {', '.join(SENTIMENT_LABELS)}.")
    rec = _get(db, ctx, feedback_id)
    prev = rec.sentiment_label
    correct_sentiment(db, rec, body.label, body.note, ctx.user.id)
    log_activity(
        db,
        ctx.workspace_id,
        ctx.user.id,
        "feedback.sentiment_corrected",
        f"Sentiment corrected from {prev} to {body.label}",
        "feedback",
        rec.id,
        {"from": prev, "to": body.label},
    )
    db.commit()
    return get_feedback(feedback_id, ctx, db)
