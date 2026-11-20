"""Dashboard analytics, trends, AI analysis triggers and job status."""

from __future__ import annotations

import uuid
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.ai.base import AIError
from app.ai.service import describe, resolve_config
from app.api.deps import DB, Ctx, ReadCtx, require
from app.core.config import get_settings
from app.core.ratelimit import ai_rate_limit
from app.models import ActivityLog, AlertEvent, FeedbackRecord, Insight, Job, Topic, User
from app.services.ai_analysis import queue_ai_analysis, select_records_for_ai
from app.services.analytics import breakdown, compare_topic_periods, data_range, distribution, load_rows, statistical_trend, timeseries, topic_stats
from app.services.demo import demo_count
from app.services.filters import FeedbackFilter, apply_filters, filter_params, tz_of
from app.services.insights import default_period
from app.services.serialize import event_out, insight_out, iso, job_out

router = APIRouter(tags=["analytics"])


def _range_info(db, ctx) -> dict:
    lo, hi = data_range(db, ctx.workspace_id)
    tz = tz_of(ctx.workspace.timezone)
    return {"earliest": lo.astimezone(tz).date().isoformat() if lo else None, "latest": hi.astimezone(tz).date().isoformat() if hi else None}


@router.get("/analytics/overview")
def overview(ctx: ReadCtx, db: DB, f: FeedbackFilter = Depends(filter_params)) -> dict:
    tz = ctx.workspace.timezone
    rows = load_rows(db, ctx.workspace_id, f, tz)
    dist = distribution(rows)
    series = timeseries(rows, tz, None, f.date_from, f.date_to)
    emerging = []
    if rows:
        d_from, d_to = (f.date_from, f.date_to) if (f.date_from and f.date_to) else default_period(db, ctx.workspace_id, tz, days=14)
        for c in compare_topic_periods(db, ctx.workspace_id, f.model_copy(update={"date_from": None, "date_to": None}), tz, d_from, d_to):
            t = c["negative_share_test"]
            if c["is_new"] or (t and t["significant"] and t["diff"] > 0):
                emerging.append(
                    {
                        "id": c["id"],
                        "name": c["name"],
                        "current_count": c["current_count"],
                        "previous_count": c["previous_count"],
                        "current_negative_share": c["current_negative_share"],
                        "previous_negative_share": c["previous_negative_share"],
                        "is_new": c["is_new"],
                        "p_value": round(t["p_value"], 4) if t else None,
                    }
                )
        emerging_period = {"from": d_from.isoformat(), "to": d_to.isoformat()}
    else:
        emerging_period = None
    insights = db.scalars(
        select(Insight).where(Insight.workspace_id == ctx.workspace_id, Insight.status == "active").order_by(Insight.created_at.desc()).limit(5)
    ).all()
    topic_names = {t.id: t.name for t in db.scalars(select(Topic).where(Topic.workspace_id == ctx.workspace_id))}
    alerts = db.scalars(
        select(AlertEvent).where(AlertEvent.workspace_id == ctx.workspace_id, AlertEvent.status == "open").order_by(AlertEvent.triggered_at.desc()).limit(5)
    ).all()
    activity = db.execute(
        select(ActivityLog, User.full_name)
        .outerjoin(User, User.id == ActivityLog.user_id)
        .where(ActivityLog.workspace_id == ctx.workspace_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(8)
    ).all()
    emotions = Counter(
        e for e in db.scalars(apply_filters(select(FeedbackRecord.primary_emotion), ctx.workspace_id, f, tz).where(FeedbackRecord.primary_emotion.is_not(None)))
    )
    return {
        "filters": f.describe(),
        "data_range": _range_info(db, ctx),
        "distribution": dist,
        "timeseries": series,
        "trend": statistical_trend(series),
        "topics": topic_stats(db, ctx.workspace_id, f, tz, limit=10),
        "by_source": breakdown(db, ctx.workspace_id, rows, "source"),
        "by_product": breakdown(db, ctx.workspace_id, rows, "product"),
        "emotions": [{"emotion": k, "count": v} for k, v in emotions.most_common()],
        "emerging": emerging[:8],
        "emerging_period": emerging_period,
        "insights": [insight_out(i, topic_names.get(i.topic_id)) for i in insights],
        "alerts": [event_out(a) for a in alerts],
        "activity": [{"id": str(a.id), "action": a.action, "summary": a.summary, "user": n, "created_at": iso(a.created_at)} for a, n in activity],
        "demo_records": demo_count(db, ctx.workspace_id),
        "ai": describe(resolve_config(db, ctx.workspace_id)),
        "min_sample_size": get_settings().min_sample_size,
    }


@router.get("/analytics/timeseries")
def series(ctx: ReadCtx, db: DB, f: FeedbackFilter = Depends(filter_params), granularity: str | None = Query(None, pattern="^(day|week|month)$")) -> dict:
    tz = ctx.workspace.timezone
    s = timeseries(load_rows(db, ctx.workspace_id, f, tz), tz, granularity, f.date_from, f.date_to)
    return {**s, "trend": statistical_trend(s), "volume_trend": statistical_trend(s, "total")}


@router.get("/analytics/breakdown")
def get_breakdown(
    ctx: ReadCtx, db: DB, dimension: str = Query("product", pattern="^(product|source)$"), f: FeedbackFilter = Depends(filter_params)
) -> list[dict]:
    return breakdown(db, ctx.workspace_id, load_rows(db, ctx.workspace_id, f, ctx.workspace.timezone), dimension)


@router.get("/trends")
def trends(
    ctx: ReadCtx,
    db: DB,
    f: FeedbackFilter = Depends(filter_params),
    granularity: str | None = Query(None, pattern="^(day|week|month)$"),
    dimension: str | None = Query(None, pattern="^(product|source|topic)$"),
) -> dict:
    """Observed history (buckets), statistical trends (regression, z-tests) and period-over-period topic changes."""
    tz = ctx.workspace.timezone
    rows = load_rows(db, ctx.workspace_id, f, tz)
    s = timeseries(rows, tz, granularity, f.date_from, f.date_to)
    d_from, d_to = (f.date_from, f.date_to) if (f.date_from and f.date_to) else default_period(db, ctx.workspace_id, tz)
    changes = compare_topic_periods(db, ctx.workspace_id, f.model_copy(update={"date_from": None, "date_to": None}), tz, d_from, d_to) if rows else []
    split = []
    zone = tz_of(tz)
    lo = f.date_from or (min(r.received_at for r in rows).astimezone(zone).date() if rows else None)
    hi = f.date_to or (max(r.received_at for r in rows).astimezone(zone).date() if rows else None)
    groups: list[tuple[str, str, FeedbackFilter]] = []
    if dimension in ("product", "source"):
        for g in breakdown(db, ctx.workspace_id, rows, dimension)[:6]:
            if g["id"]:
                gid = uuid.UUID(g["id"])
                groups.append((g["id"], g["name"], f.model_copy(update={"product_ids": [gid]} if dimension == "product" else {"source_ids": [gid]})))
    elif dimension == "topic":
        for t in topic_stats(db, ctx.workspace_id, f, tz, limit=6):
            groups.append((t["id"], t["name"], f.model_copy(update={"topic_ids": [uuid.UUID(t["id"])]})))
    for gid_s, name, gf in groups:
        gs = timeseries(load_rows(db, ctx.workspace_id, gf, tz), tz, s["granularity"], lo, hi)
        split.append({"id": gid_s, "name": name, "series": gs["buckets"], "trend": statistical_trend(gs)})
    return {
        "observed": s,
        "statistical": {
            "negative_share": statistical_trend(s),
            "volume": statistical_trend(s, "total"),
            "average_score": statistical_trend(s, "average_score"),
        },
        "period_comparison": {"current": [d_from.isoformat(), d_to.isoformat()], "topics": changes},
        "split": split,
        "notes": [
            "Observed: counts per time bucket, exactly as stored.",
            "Statistical: regression and z-tests; buckets below the minimum sample size are excluded.",
            "Neither establishes a cause. AI interpretations are available in the AI Analyst and Insights, and are labelled.",
        ],
        "min_sample_size": get_settings().min_sample_size,
    }


# ------------------------------------------------------------------------------------ AI analysis


class AIRunIn(BaseModel):
    feedback_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)
    only_unanalysed: bool = True


@router.get("/analysis/status")
def ai_status(ctx: ReadCtx, db: DB) -> dict:
    counts = dict(
        db.execute(
            select(FeedbackRecord.ai_status, func.count())
            .where(FeedbackRecord.workspace_id == ctx.workspace_id, FeedbackRecord.is_archived.is_(False))
            .group_by(FeedbackRecord.ai_status)
        ).all()
    )
    methods = dict(
        db.execute(
            select(FeedbackRecord.sentiment_method, func.count())
            .where(FeedbackRecord.workspace_id == ctx.workspace_id, FeedbackRecord.is_archived.is_(False))
            .group_by(FeedbackRecord.sentiment_method)
        ).all()
    )
    running = db.scalars(
        select(Job)
        .where(Job.workspace_id == ctx.workspace_id, Job.job_type == "ai_analyze", Job.status.in_(("queued", "running")))
        .order_by(Job.created_at.desc())
    ).all()
    return {
        "ai": describe(resolve_config(db, ctx.workspace_id)),
        "ai_status_counts": counts,
        "method_counts": {k or "none": v for k, v in methods.items()},
        "active_jobs": [job_out(j) for j in running],
        "max_records_per_run": get_settings().ai_max_records_per_run,
    }


@router.post("/analysis/run", dependencies=[Depends(require("analysis:run")), Depends(ai_rate_limit)])
def run_ai(body: AIRunIn, ctx: Ctx, db: DB) -> dict:
    ids = select_records_for_ai(db, ctx.workspace_id, body.feedback_ids or None, body.only_unanalysed and not body.feedback_ids)
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No records to analyse (all selected records are already analysed by AI).")
    try:
        job = queue_ai_analysis(db, ctx.workspace_id, ids, ctx.user.id)
    except AIError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    db.commit()
    return {"job": job_out(job), "records": len(ids)}


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict:
    job = db.get(Job, job_id)
    if job is None or job.workspace_id != ctx.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return job_out(job)
