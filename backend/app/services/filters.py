"""One filter definition shared by the feedback list, dashboard cards, charts, exports and reports.

Using the same function everywhere guarantees that summary cards and charts are computed over the same records.
Date filters are *calendar dates in the workspace time zone*, inclusive on both ends.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, exists, or_, select

from app.models import FeedbackRecord, FeedbackTopic, Tag, feedback_tags


class FeedbackFilter(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    source_ids: list[uuid.UUID] = []
    product_ids: list[uuid.UUID] = []
    topic_ids: list[uuid.UUID] = []
    tag_ids: list[uuid.UUID] = []
    sentiments: list[str] = []
    q: str | None = None
    needs_review: bool | None = None
    include_archived: bool = False
    archived_only: bool = False
    segment: str | None = None
    language: str | None = None
    method: str | None = None
    is_demo: bool | None = None

    def describe(self) -> dict:
        return {
            k: (str(v) if not isinstance(v, (list, bool, type(None))) else ([str(x) for x in v] if isinstance(v, list) else v))
            for k, v in self.model_dump().items()
            if v not in (None, [], False, "")
        }


def filter_params(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    source_id: list[uuid.UUID] = Query(default=[]),
    product_id: list[uuid.UUID] = Query(default=[]),
    topic_id: list[uuid.UUID] = Query(default=[]),
    tag_id: list[uuid.UUID] = Query(default=[]),
    sentiment: list[str] = Query(default=[]),
    q: str | None = Query(None, max_length=200),
    needs_review: bool | None = Query(None),
    include_archived: bool = Query(False),
    archived_only: bool = Query(False),
    segment: str | None = Query(None, max_length=120),
    language: str | None = Query(None, max_length=16),
    method: str | None = Query(None, max_length=20),
    is_demo: bool | None = Query(None),
) -> FeedbackFilter:
    return FeedbackFilter(
        date_from=date_from,
        date_to=date_to,
        source_ids=source_id,
        product_ids=product_id,
        topic_ids=topic_id,
        tag_ids=tag_id,
        sentiments=sentiment,
        q=q,
        needs_review=needs_review,
        include_archived=include_archived,
        archived_only=archived_only,
        segment=segment,
        language=language,
        method=method,
        is_demo=is_demo,
    )


def tz_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:  # noqa: BLE001 - unknown zone name
        return ZoneInfo("UTC")


def local_day_bounds(d_from: date | None, d_to: date | None, tz: ZoneInfo) -> tuple[datetime | None, datetime | None]:
    """Inclusive local calendar dates -> half-open UTC instants [start, end)."""
    start = datetime.combine(d_from, time.min, tzinfo=tz).astimezone(UTC) if d_from else None
    end = datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC) if d_to else None
    return start, end


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_filters(stmt: Select, workspace_id: uuid.UUID, f: FeedbackFilter, tz_name: str = "UTC") -> Select:
    FR = FeedbackRecord
    stmt = stmt.where(FR.workspace_id == workspace_id)
    if f.archived_only:
        stmt = stmt.where(FR.is_archived.is_(True))
    elif not f.include_archived:
        stmt = stmt.where(FR.is_archived.is_(False))
    start, end = local_day_bounds(f.date_from, f.date_to, tz_of(tz_name))
    if start is not None:
        stmt = stmt.where(FR.received_at >= start)
    if end is not None:
        stmt = stmt.where(FR.received_at < end)
    if f.source_ids:
        stmt = stmt.where(FR.source_id.in_(f.source_ids))
    if f.product_ids:
        stmt = stmt.where(FR.product_id.in_(f.product_ids))
    if f.sentiments:
        labels = [s for s in f.sentiments if s != "unanalyzed"]
        conds = []
        if labels:
            conds.append(FR.sentiment_label.in_(labels))
        if "unanalyzed" in f.sentiments:
            conds.append(FR.sentiment_label.is_(None))
        stmt = stmt.where(or_(*conds))
    if f.topic_ids:
        stmt = stmt.where(exists().where(FeedbackTopic.feedback_id == FR.id, FeedbackTopic.topic_id.in_(f.topic_ids)))
    if f.tag_ids:
        stmt = stmt.where(exists().where(feedback_tags.c.feedback_id == FR.id, feedback_tags.c.tag_id.in_(f.tag_ids)))
    if f.q:
        term = f"%{escape_like(f.q.strip())}%"
        stmt = stmt.where(
            or_(
                FR.text.ilike(term, escape="\\"),
                FR.title.ilike(term, escape="\\"),
                FR.customer_ref.ilike(term, escape="\\"),
                exists().where(feedback_tags.c.feedback_id == FR.id, feedback_tags.c.tag_id == Tag.id, Tag.name.ilike(term, escape="\\")),
            )
        )
    if f.needs_review is not None:
        stmt = stmt.where(FR.needs_review.is_(f.needs_review))
    if f.segment:
        stmt = stmt.where(FR.customer_segment == f.segment)
    if f.language:
        stmt = stmt.where(FR.language == f.language)
    if f.method:
        stmt = stmt.where(FR.sentiment_method == f.method)
    if f.is_demo is not None:
        stmt = stmt.where(FR.is_demo.is_(f.is_demo))
    return stmt


def filtered_ids_subquery(workspace_id: uuid.UUID, f: FeedbackFilter, tz_name: str):
    return apply_filters(select(FeedbackRecord.id), workspace_id, f, tz_name).subquery()
