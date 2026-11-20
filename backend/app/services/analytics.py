"""Deterministic analytics computed from stored records.

All figures come from the database for the given filter. Percentages use the number of *classified* records
(records with a sentiment label) as the denominator; unclassified records are reported separately.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import FeedbackRecord, FeedbackSource, FeedbackTopic, Product, Topic
from app.services.filters import FeedbackFilter, apply_filters, filtered_ids_subquery, tz_of
from app.services.stats import linear_trend, pct, two_proportion_ztest

LABELS = ("positive", "negative", "neutral", "mixed", "uncertain")


@dataclass
class Row:
    id: uuid.UUID
    received_at: datetime
    label: str | None
    score: float | None
    product_id: uuid.UUID | None
    source_id: uuid.UUID | None
    method: str | None
    rating: float | None
    rating_max: float | None


def load_rows(db: Session, workspace_id: uuid.UUID, f: FeedbackFilter, tz_name: str) -> list[Row]:
    FR = FeedbackRecord
    stmt = select(FR.id, FR.received_at, FR.sentiment_label, FR.sentiment_score, FR.product_id, FR.source_id, FR.sentiment_method, FR.rating, FR.rating_max)
    stmt = apply_filters(stmt, workspace_id, f, tz_name)
    out = []
    for r in db.execute(stmt):
        ra = r.received_at if r.received_at.tzinfo else r.received_at.replace(tzinfo=UTC)
        out.append(Row(r.id, ra, r.sentiment_label, r.sentiment_score, r.product_id, r.source_id, r.sentiment_method, r.rating, r.rating_max))
    return out


def distribution(rows: list[Row]) -> dict:
    counts = Counter(r.label for r in rows if r.label)
    classified = sum(counts.values())
    scores = [r.score for r in rows if r.score is not None]
    ratings = [100.0 * r.rating / r.rating_max for r in rows if r.rating is not None and r.rating_max]
    methods = Counter(r.method for r in rows if r.method)
    return {
        "total": len(rows),
        "classified": classified,
        "unclassified": len(rows) - classified,
        "counts": {k: counts.get(k, 0) for k in LABELS},
        "percentages": {k: pct(counts.get(k, 0), classified) for k in LABELS},
        "average_score": round(sum(scores) / len(scores), 3) if scores else None,
        "average_score_n": len(scores),
        "average_rating_pct": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "average_rating_n": len(ratings),
        "methods": {k: methods.get(k, 0) for k in ("lexicon", "ai", "manual")},
        "denominator_note": "Percentages are shares of classified records. Average score excludes records without a numeric score (e.g. manual corrections).",
    }


def topic_stats(db: Session, workspace_id: uuid.UUID, f: FeedbackFilter, tz_name: str, limit: int | None = None) -> list[dict]:
    """Per-topic volume and sentiment. Aspect sentiment is used when available, otherwise the record's sentiment."""
    ids = filtered_ids_subquery(workspace_id, f, tz_name)
    label = func.coalesce(FeedbackTopic.sentiment, FeedbackRecord.sentiment_label)
    stmt = (
        select(Topic.id, Topic.name, Topic.origin, Topic.review_status, label.label("label"), func.count().label("n"))
        .join(FeedbackTopic, FeedbackTopic.topic_id == Topic.id)
        .join(FeedbackRecord, FeedbackRecord.id == FeedbackTopic.feedback_id)
        .where(Topic.workspace_id == workspace_id, FeedbackTopic.feedback_id.in_(select(ids.c.id)))
        .group_by(Topic.id, Topic.name, Topic.origin, Topic.review_status, label)
    )
    agg: dict[uuid.UUID, dict] = {}
    for tid, name, origin, review, lab, n in db.execute(stmt):
        t = agg.setdefault(
            tid, {"id": str(tid), "name": name, "origin": origin, "review_status": review, "count": 0, **{k: 0 for k in LABELS}, "unclassified": 0}
        )
        t["count"] += n
        if lab in LABELS:
            t[lab] += n
        else:
            t["unclassified"] += n
    min_n = get_settings().min_sample_size
    out = []
    for t in agg.values():
        classified = t["count"] - t["unclassified"]
        t["negative_share"] = pct(t["negative"], classified)
        t["positive_share"] = pct(t["positive"], classified)
        t["low_sample"] = t["count"] < min_n
        out.append(t)
    out.sort(key=lambda t: (-t["count"], t["name"]))
    return out[:limit] if limit else out


def breakdown(db: Session, workspace_id: uuid.UUID, rows: list[Row], dimension: str) -> list[dict]:
    key = (lambda r: r.product_id) if dimension == "product" else (lambda r: r.source_id)
    model = Product if dimension == "product" else FeedbackSource
    names = {o.id: o.name for o in db.scalars(select(model).where(model.workspace_id == workspace_id))}
    groups: dict[uuid.UUID | None, list[Row]] = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    min_n = get_settings().min_sample_size
    out = []
    for gid, items in groups.items():
        d = distribution(items)
        out.append(
            {
                "id": str(gid) if gid else None,
                "name": names.get(gid, "Unknown") if gid else f"No {dimension}",
                "count": d["total"],
                "classified": d["classified"],
                "counts": d["counts"],
                "negative_share": d["percentages"]["negative"],
                "positive_share": d["percentages"]["positive"],
                "average_score": d["average_score"],
                "low_sample": d["total"] < min_n,
            }
        )
    out.sort(key=lambda x: -x["count"])
    return out


# ------------------------------------------------------------------------------------------ time series


def bucket_start(dt: datetime, granularity: str, tz) -> date:
    local = dt.astimezone(tz).date()
    if granularity == "week":
        return local - timedelta(days=local.weekday())
    if granularity == "month":
        return local.replace(day=1)
    return local


def _next_bucket(d: date, granularity: str) -> date:
    if granularity == "week":
        return d + timedelta(days=7)
    if granularity == "month":
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return d + timedelta(days=1)


def auto_granularity(start: date, end: date) -> str:
    span = (end - start).days
    if span <= 45:
        return "day"
    if span <= 280:
        return "week"
    return "month"


def timeseries(rows: list[Row], tz_name: str, granularity: str | None = None, d_from: date | None = None, d_to: date | None = None) -> dict:
    tz = tz_of(tz_name)
    if not rows and not (d_from and d_to):
        return {"granularity": granularity or "day", "buckets": [], "min_bucket_size": get_settings().min_sample_size}
    local_dates = [r.received_at.astimezone(tz).date() for r in rows]
    start = d_from or min(local_dates)
    end = d_to or max(local_dates)
    if end < start:
        start, end = end, start
    granularity = granularity if granularity in ("day", "week", "month") else auto_granularity(start, end)
    # Keep responses bounded.
    while granularity != "month" and len(range((end - start).days)) / (7 if granularity == "week" else 1) > 400:
        granularity = "week" if granularity == "day" else "month"
    buckets: dict[date, list[Row]] = {}
    cur = bucket_start(datetime.combine(start, datetime.min.time(), tzinfo=tz), granularity, tz)
    last = bucket_start(datetime.combine(end, datetime.min.time(), tzinfo=tz), granularity, tz)
    while cur <= last:
        buckets[cur] = []
        cur = _next_bucket(cur, granularity)
    for r in rows:
        b = bucket_start(r.received_at, granularity, tz)
        if b in buckets:
            buckets[b].append(r)
    min_n = get_settings().min_sample_size
    out = []
    for b, items in buckets.items():
        d = distribution(items)
        out.append(
            {
                "bucket": b.isoformat(),
                "total": d["total"],
                "classified": d["classified"],
                **d["counts"],
                "negative_share": d["percentages"]["negative"],
                "positive_share": d["percentages"]["positive"],
                "average_score": d["average_score"],
                "low_sample": d["total"] < min_n,
            }
        )
    return {"granularity": granularity, "buckets": out, "min_bucket_size": min_n}


def statistical_trend(series: dict, metric: str = "negative_share") -> dict:
    """Linear trend over buckets that meet the minimum sample size."""
    pts = [b[metric] for b in series["buckets"] if not b["low_sample"] and b[metric] is not None]
    lt = linear_trend([float(p) for p in pts])
    if lt is None:
        return {
            "metric": metric,
            "status": "insufficient_data",
            "points_used": len(pts),
            "note": "Needs at least 4 time buckets that each meet the minimum sample size.",
        }
    direction = "flat"
    if lt.significant:
        direction = "up" if lt.slope > 0 else "down"
    return {
        "metric": metric,
        "status": "ok",
        "direction": direction,
        "slope_per_bucket": round(lt.slope, 3),
        "p_value": round(lt.p_value, 4),
        "r_squared": round(lt.r_squared, 3),
        "points_used": lt.n_points,
        "significant": lt.significant,
        "method": lt.method,
        "note": "Statistical association over time only; it does not establish a cause.",
    }


# ------------------------------------------------------------------------------------------ period comparison


def previous_period(d_from: date, d_to: date) -> tuple[date, date]:
    length = (d_to - d_from).days + 1
    prev_to = d_from - timedelta(days=1)
    return prev_to - timedelta(days=length - 1), prev_to


def compare_topic_periods(db: Session, workspace_id: uuid.UUID, base: FeedbackFilter, tz_name: str, d_from: date, d_to: date) -> list[dict]:
    """Per-topic change between [d_from, d_to] and the preceding period of equal length."""
    p_from, p_to = previous_period(d_from, d_to)
    cur_f = base.model_copy(update={"date_from": d_from, "date_to": d_to})
    prev_f = base.model_copy(update={"date_from": p_from, "date_to": p_to})
    cur_rows = load_rows(db, workspace_id, cur_f, tz_name)
    prev_rows = load_rows(db, workspace_id, prev_f, tz_name)
    cur_total, prev_total = len(cur_rows), len(prev_rows)
    cur = {t["id"]: t for t in topic_stats(db, workspace_id, cur_f, tz_name)}
    prev = {t["id"]: t for t in topic_stats(db, workspace_id, prev_f, tz_name)}
    min_n = get_settings().min_sample_size
    out = []
    for tid in set(cur) | set(prev):
        c = cur.get(tid) or {**prev[tid], "count": 0, "negative": 0, "positive": 0, "neutral": 0, "mixed": 0, "uncertain": 0, "unclassified": 0}
        p = prev.get(tid) or {"count": 0, "negative": 0, "positive": 0}
        c_cls = c["count"] - c.get("unclassified", 0)
        p_cls = p["count"] - p.get("unclassified", 0)
        neg_test = two_proportion_ztest(p["negative"], p_cls, c["negative"], c_cls) if c_cls >= min_n and p_cls >= min_n else None
        share_test = two_proportion_ztest(p["count"], prev_total, c["count"], cur_total) if prev_total >= min_n and cur_total >= min_n else None
        out.append(
            {
                "id": tid,
                "name": c["name"],
                "current_count": c["count"],
                "previous_count": p["count"],
                "current_negative": c["negative"],
                "previous_negative": p["negative"],
                "current_negative_share": pct(c["negative"], c_cls),
                "previous_negative_share": pct(p["negative"], p_cls),
                "current_volume_share": pct(c["count"], cur_total),
                "previous_volume_share": pct(p["count"], prev_total),
                "negative_share_test": neg_test.__dict__ if neg_test else None,
                "volume_share_test": share_test.__dict__ if share_test else None,
                "is_new": p["count"] == 0 and c["count"] >= min_n,
                "low_sample": c["count"] < min_n or p["count"] < min_n,
            }
        )
    out.sort(key=lambda t: -t["current_count"])
    return out


def data_range(db: Session, workspace_id: uuid.UUID) -> tuple[datetime | None, datetime | None]:
    lo, hi = db.execute(
        select(func.min(FeedbackRecord.received_at), func.max(FeedbackRecord.received_at)).where(
            FeedbackRecord.workspace_id == workspace_id, FeedbackRecord.is_archived.is_(False)
        )
    ).one()
    return lo, hi
