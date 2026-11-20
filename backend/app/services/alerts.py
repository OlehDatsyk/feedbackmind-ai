"""Smart alerts: user-configured rules evaluated against stored data.

An alert fires only when its rule's condition is met for the window, the minimum count is reached, and the rule is
not in its cooldown period. Each event records the figures behind it and links to supporting records.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import AlertEvent, AlertRule, FeedbackRecord, Job, Topic, Workspace
from app.services import jobs
from app.services.analytics import distribution, load_rows, topic_stats
from app.services.filters import FeedbackFilter, apply_filters, tz_of

ALERT_TYPES: dict[str, dict] = {
    "negative_spike": {"label": "Sudden increase in negative feedback", "threshold_label": "Increase vs previous window (%)", "default_threshold": 50},
    "negative_share": {"label": "Negative share above threshold", "threshold_label": "Negative share (%)", "default_threshold": 40},
    "sentiment_drop": {"label": "Significant drop in average sentiment", "threshold_label": "Drop in average score (0-2 scale)", "default_threshold": 0.2},
    "volume_spike": {"label": "Unusual feedback volume", "threshold_label": "Increase vs previous window (%)", "default_threshold": 100},
    "new_topic": {"label": "New recurring topic", "threshold_label": "(not used)", "default_threshold": 0},
    "product_complaints": {"label": "Increase in complaints about a product", "threshold_label": "Increase vs previous window (%)", "default_threshold": 50},
    "unresolved_review": {"label": "Important unresolved issues", "threshold_label": "Unresolved negative records flagged for review", "default_threshold": 5},
}


def _windows(tz_name: str, days: int) -> tuple:
    tz = tz_of(tz_name)
    today = datetime.now(UTC).astimezone(tz).date()
    cur_from = today - timedelta(days=days - 1)
    prev_to = cur_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=days - 1)
    return cur_from, today, prev_from, prev_to


def _filter(rule: AlertRule, d_from, d_to) -> FeedbackFilter:
    return FeedbackFilter(
        date_from=d_from,
        date_to=d_to,
        product_ids=[rule.product_id] if rule.product_id else [],
        topic_ids=[rule.topic_id] if rule.topic_id else [],
    )


def _evidence(db: Session, workspace_id: uuid.UUID, f: FeedbackFilter, tz_name: str, labels: tuple[str, ...] | None, limit: int = 10) -> list[str]:
    stmt = apply_filters(select(FeedbackRecord.id), workspace_id, f, tz_name)
    if labels:
        stmt = stmt.where(FeedbackRecord.sentiment_label.in_(labels))
    return [str(i) for i in db.scalars(stmt.order_by(FeedbackRecord.received_at.desc()).limit(limit))]


def _pct_increase(cur: float, prev: float) -> float | None:
    if prev <= 0:
        return None
    return round(100.0 * (cur - prev) / prev, 1)


def evaluate_rule(db: Session, rule: AlertRule, tz_name: str, now: datetime | None = None) -> AlertEvent | None:
    now = now or utcnow()
    rule.last_evaluated_at = now
    if not rule.is_enabled:
        return None
    last = rule.last_triggered_at
    if last is not None:
        last = last if last.tzinfo else last.replace(tzinfo=UTC)
        if now - last < timedelta(hours=rule.cooldown_hours):
            return None
    ws = rule.workspace_id
    cur_from, cur_to, prev_from, prev_to = _windows(tz_name, max(1, rule.window_days))
    cur_f, prev_f = _filter(rule, cur_from, cur_to), _filter(rule, prev_from, prev_to)
    scope = []
    if rule.product_id:
        from app.models import Product

        p = db.get(Product, rule.product_id)
        scope.append(f"product '{p.name}'" if p else "the selected product")
    if rule.topic_id:
        t = db.get(Topic, rule.topic_id)
        scope.append(f"topic '{t.name}'" if t else "the selected topic")
    scope_txt = f" for {' and '.join(scope)}" if scope else ""
    window_txt = f"the last {rule.window_days} day(s) ({cur_from} to {cur_to})"
    prev_txt = f"the previous {rule.window_days} day(s) ({prev_from} to {prev_to})"
    t = rule.alert_type
    metrics: dict = {
        "window": [cur_from.isoformat(), cur_to.isoformat()],
        "previous_window": [prev_from.isoformat(), prev_to.isoformat()],
        "threshold": rule.threshold,
        "min_count": rule.min_count,
    }
    title = explanation = None
    labels: tuple[str, ...] | None = None
    severity = "medium"

    if t in ("negative_spike", "product_complaints"):
        if t == "product_complaints" and not rule.product_id:
            return None
        cur = distribution(load_rows(db, ws, cur_f, tz_name))
        prev = distribution(load_rows(db, ws, prev_f, tz_name))
        c, p = cur["counts"]["negative"], prev["counts"]["negative"]
        inc = _pct_increase(c, p)
        metrics.update({"current_negative": c, "previous_negative": p, "increase_pct": inc})
        if c >= rule.min_count and (inc is None or inc >= rule.threshold):
            labels = ("negative",)
            title = f"Negative feedback increased{scope_txt}"
            change = f"an increase of {inc}%" if inc is not None else "with no negative feedback in the previous window"
            explanation = f"{c} negative records in {window_txt} versus {p} in {prev_txt}, {change}. Rule: at least {rule.min_count} records and an increase of {rule.threshold:g}% or more."
            severity = "high" if c >= 2 * rule.min_count else "medium"
    elif t == "negative_share":
        cur = distribution(load_rows(db, ws, cur_f, tz_name))
        share = cur["percentages"]["negative"]
        metrics.update({"classified": cur["classified"], "negative": cur["counts"]["negative"], "negative_share": share})
        if cur["classified"] >= rule.min_count and share is not None and share >= rule.threshold:
            labels = ("negative",)
            title = f"Negative share is {share}%{scope_txt}"
            explanation = f"{cur['counts']['negative']} of {cur['classified']} classified records in {window_txt} are negative ({share}%), at or above the {rule.threshold:g}% threshold."
            severity = "high" if share >= rule.threshold + 15 else "medium"
    elif t == "sentiment_drop":
        cur = distribution(load_rows(db, ws, cur_f, tz_name))
        prev = distribution(load_rows(db, ws, prev_f, tz_name))
        metrics.update(
            {
                "current_average": cur["average_score"],
                "previous_average": prev["average_score"],
                "current_n": cur["average_score_n"],
                "previous_n": prev["average_score_n"],
            }
        )
        if cur["average_score_n"] >= rule.min_count and prev["average_score_n"] >= rule.min_count:
            drop = round(prev["average_score"] - cur["average_score"], 3)
            metrics["drop"] = drop
            if drop >= rule.threshold:
                labels = ("negative", "mixed")
                title = f"Average sentiment dropped by {drop:.2f}{scope_txt}"
                explanation = f"Average sentiment score fell from {prev['average_score']:+.2f} ({prev['average_score_n']} records, {prev_txt}) to {cur['average_score']:+.2f} ({cur['average_score_n']} records, {window_txt}), a drop of {drop:.2f} (threshold {rule.threshold:g})."
    elif t == "volume_spike":
        c, p = len(load_rows(db, ws, cur_f, tz_name)), len(load_rows(db, ws, prev_f, tz_name))
        inc = _pct_increase(c, p)
        metrics.update({"current_volume": c, "previous_volume": p, "increase_pct": inc})
        if c >= rule.min_count and inc is not None and inc >= rule.threshold:
            title = f"Feedback volume up {inc}%{scope_txt}"
            explanation = f"{c} records in {window_txt} versus {p} in {prev_txt} (+{inc}%, threshold {rule.threshold:g}%)."
    elif t == "new_topic":
        cur_t = {x["id"]: x for x in topic_stats(db, ws, cur_f, tz_name)}
        prev_t = {x["id"]: x for x in topic_stats(db, ws, prev_f, tz_name)}
        new = [x for tid, x in cur_t.items() if x["count"] >= rule.min_count and tid not in prev_t]
        metrics["new_topics"] = [{"name": x["name"], "count": x["count"]} for x in new]
        if new:
            title = "New recurring topic: " + ", ".join(x["name"] for x in new[:3])
            explanation = (
                "; ".join(f"{x['name']}: {x['count']} records in {window_txt} and none in {prev_txt}" for x in new)
                + f". Rule: at least {rule.min_count} records."
            )
            cur_f = cur_f.model_copy(update={"topic_ids": [uuid.UUID(x["id"]) for x in new]})
    elif t == "unresolved_review":
        stmt = apply_filters(
            select(FeedbackRecord.id), ws, FeedbackFilter(product_ids=cur_f.product_ids, topic_ids=cur_f.topic_ids, needs_review=True), tz_name
        )
        stmt = stmt.where(FeedbackRecord.sentiment_label == "negative", FeedbackRecord.received_at < now - timedelta(days=rule.window_days))
        ids = list(db.scalars(stmt.limit(500)))
        metrics["unresolved"] = len(ids)
        if len(ids) >= max(rule.threshold, 1):
            title = f"{len(ids)} negative records flagged for review are unresolved{scope_txt}"
            explanation = f"{len(ids)} negative records marked 'needs review' are older than {rule.window_days} day(s) (threshold {rule.threshold:g})."
            evidence = [str(i) for i in ids[:10]]
            return _create_event(db, rule, title, explanation, metrics, evidence, cur_from, cur_to, tz_name, "high", now)
    if title is None or explanation is None:
        return None
    evidence = _evidence(db, ws, cur_f, tz_name, labels)
    return _create_event(db, rule, title, explanation, metrics, evidence, cur_from, cur_to, tz_name, severity, now)


def _create_event(db, rule, title, explanation, metrics, evidence, cur_from, cur_to, tz_name, severity, now) -> AlertEvent:
    from app.services.filters import local_day_bounds

    start, end = local_day_bounds(cur_from, cur_to, tz_of(tz_name))
    ev = AlertEvent(
        workspace_id=rule.workspace_id,
        rule_id=rule.id,
        alert_type=rule.alert_type,
        title=title[:300],
        explanation=explanation,
        severity=severity,
        metrics=metrics,
        evidence_ids=evidence,
        window_start=start,
        window_end=end,
        triggered_at=now,
    )
    db.add(ev)
    rule.last_triggered_at = now
    return ev


def evaluate_workspace(db: Session, workspace_id: uuid.UUID) -> list[AlertEvent]:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        return []
    events = []
    for rule in db.scalars(select(AlertRule).where(AlertRule.workspace_id == workspace_id, AlertRule.is_enabled.is_(True))):
        ev = evaluate_rule(db, rule, ws.timezone)
        if ev is not None:
            events.append(ev)
    db.flush()
    return events


@jobs.handler("alerts_evaluate")
def run_alert_evaluation(db: Session, job: Job) -> dict:
    assert job.workspace_id is not None
    events = evaluate_workspace(db, job.workspace_id)
    return {"triggered": len(events)}


def schedule_periodic_evaluation(db: Session) -> int:
    ws_ids = set(db.scalars(select(AlertRule.workspace_id).where(AlertRule.is_enabled.is_(True)).distinct()))
    pending = set(db.scalars(select(Job.workspace_id).where(Job.job_type == "alerts_evaluate", Job.status.in_(("queued", "running")))))
    n = 0
    for ws_id in ws_ids - pending:
        jobs.enqueue(db, "alerts_evaluate", ws_id, {"reason": "schedule"})
        n += 1
    return n


DEFAULT_RULES = [
    ("Negative feedback spike (7 days)", "negative_spike", 50.0, 7, 5),
    ("Negative share above 40% (7 days)", "negative_share", 40.0, 7, 10),
    ("New recurring topic (14 days)", "new_topic", 0.0, 14, 5),
]
