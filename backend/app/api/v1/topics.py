"""Topic management: list with statistics, create, rename, edit keywords, approve AI topics, merge, delete."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, ReadCtx, require
from app.models import FeedbackRecord, FeedbackTopic, Topic
from app.services import jobs
from app.services.activity import log_activity
from app.services.analytics import topic_stats
from app.services.feedback import owned
from app.services.filters import FeedbackFilter, filter_params
from app.services.serialize import feedback_summary, job_out, topic_out
from app.services.topic_ops import delete_topic, merge_topics, suggest_topics

router = APIRouter(prefix="/topics", tags=["topics"])
Manage = Depends(require("topics:manage"))


class TopicIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    keywords: list[str] = Field(default_factory=list, max_length=100)


class TopicUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    keywords: list[str] | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    review_status: str | None = Field(default=None, pattern="^(approved|pending_review)$")


class MergeIn(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID


def _clean_keywords(words: list[str]) -> list[str]:
    return list(dict.fromkeys(w.strip().lower()[:60] for w in words if w and w.strip()))


@router.get("")
def list_topics(ctx: ReadCtx, db: DB, f: FeedbackFilter = Depends(filter_params), include_inactive: bool = False) -> list[dict]:
    stats = {s["id"]: s for s in topic_stats(db, ctx.workspace_id, f, ctx.workspace.timezone)}
    stmt = select(Topic).where(Topic.workspace_id == ctx.workspace_id)
    if not include_inactive:
        stmt = stmt.where(Topic.is_active.is_(True), Topic.merged_into_id.is_(None))
    topics = db.scalars(stmt.order_by(Topic.name)).all()
    out = [topic_out(t, stats.get(str(t.id))) for t in topics]
    out.sort(key=lambda t: (-(t["stats"]["count"] if t["stats"] else 0), t["name"]))
    return out


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Manage])
def create_topic(body: TopicIn, ctx: ReadCtx, db: DB) -> dict:
    t = Topic(workspace_id=ctx.workspace_id, name=body.name.strip(), description=body.description, keywords=_clean_keywords(body.keywords), origin="custom")
    db.add(t)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A topic with this name already exists.") from None
    log_activity(db, ctx.workspace_id, ctx.user.id, "topic.created", f"Created topic {t.name}", "topic", t.id)
    db.commit()
    return topic_out(t)


@router.get("/suggestions")
def suggestions(ctx: ReadCtx, db: DB) -> dict:
    return suggest_topics(db, ctx.workspace_id, ctx.workspace.timezone)


@router.post("/reapply-rules", dependencies=[Manage])
def reapply(ctx: ReadCtx, db: DB) -> dict:
    job = jobs.enqueue(db, "topics_reapply", ctx.workspace_id, {}, ctx.user.id)
    db.commit()
    return job_out(job)


@router.post("/merge", dependencies=[Manage])
def merge(body: MergeIn, ctx: ReadCtx, db: DB) -> dict:
    if body.source_id == body.target_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose two different topics.")
    source = owned(db, Topic, ctx.workspace_id, body.source_id, "Topic")
    target = owned(db, Topic, ctx.workspace_id, body.target_id, "Topic")
    if target.merged_into_id is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The target topic has itself been merged; choose its replacement.")
    moved = merge_topics(db, ctx.workspace_id, source, target)
    log_activity(db, ctx.workspace_id, ctx.user.id, "topic.merged", f"Merged {source.name} into {target.name}", "topic", target.id, {"moved_links": moved})
    db.commit()
    return {"target": topic_out(target), "moved_links": moved}


@router.get("/{topic_uuid}")
def get_topic(topic_uuid: uuid.UUID, ctx: ReadCtx, db: DB, f: FeedbackFilter = Depends(filter_params)) -> dict:
    t = owned(db, Topic, ctx.workspace_id, topic_uuid, "Topic")
    tf = f.model_copy(update={"topic_ids": [t.id]})
    stats = next((s for s in topic_stats(db, ctx.workspace_id, tf, ctx.workspace.timezone) if s["id"] == str(t.id)), None)
    examples = {}
    for label in ("negative", "positive", "neutral"):
        lab = func.coalesce(FeedbackTopic.sentiment, FeedbackRecord.sentiment_label)
        stmt = (
            select(FeedbackRecord)
            .join(FeedbackTopic, FeedbackTopic.feedback_id == FeedbackRecord.id)
            .where(FeedbackRecord.workspace_id == ctx.workspace_id, FeedbackTopic.topic_id == t.id, lab == label, FeedbackRecord.is_archived.is_(False))
            .order_by(FeedbackRecord.received_at.desc())
            .limit(3)
        )
        examples[label] = [feedback_summary(r) for r in db.scalars(stmt).unique()]
    from app.services.analytics import load_rows, statistical_trend, timeseries

    series = timeseries(load_rows(db, ctx.workspace_id, tf, ctx.workspace.timezone), ctx.workspace.timezone, None, f.date_from, f.date_to)
    return {**topic_out(t, stats), "examples": examples, "series": series, "trend": statistical_trend(series)}


@router.patch("/{topic_id}", dependencies=[Manage])
def update_topic(topic_id: uuid.UUID, body: TopicUpdate, ctx: ReadCtx, db: DB) -> dict:
    t = owned(db, Topic, ctx.workspace_id, topic_id, "Topic")
    data = body.model_dump(exclude_none=True)
    if "keywords" in data:
        data["keywords"] = _clean_keywords(data["keywords"])
    if "name" in data:
        data["name"] = data["name"].strip()
    for k, v in data.items():
        setattr(t, k, v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A topic with this name already exists.") from None
    log_activity(db, ctx.workspace_id, ctx.user.id, "topic.updated", f"Updated topic {t.name}", "topic", t.id, {"fields": list(data)})
    db.commit()
    return topic_out(t)


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Manage])
def remove_topic(topic_id: uuid.UUID, ctx: ReadCtx, db: DB) -> Response:
    t = owned(db, Topic, ctx.workspace_id, topic_id, "Topic")
    name = t.name
    delete_topic(db, t)
    log_activity(db, ctx.workspace_id, ctx.user.id, "topic.deleted", f"Deleted topic {name}", "topic", topic_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
