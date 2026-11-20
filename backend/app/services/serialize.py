"""Serialisers for API responses (explicit fields; never return secrets)."""

from __future__ import annotations

from app.models import AlertEvent, AlertRule, FeedbackRecord, ImportJob, Insight, Job, Report, Topic


def iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def feedback_summary(r: FeedbackRecord) -> dict:
    return {
        "id": str(r.id),
        "text": r.text,
        "title": r.title,
        "received_at": iso(r.received_at),
        "source": {"id": str(r.source.id), "name": r.source.name, "kind": r.source.kind} if r.source else None,
        "product": {"id": str(r.product.id), "name": r.product.name} if r.product else None,
        "customer_ref": r.customer_ref,
        "customer_segment": r.customer_segment,
        "language": r.language,
        "rating": r.rating,
        "rating_max": r.rating_max,
        "sentiment": {"label": r.sentiment_label, "score": r.sentiment_score, "confidence": r.sentiment_confidence, "method": r.sentiment_method},
        "primary_emotion": r.primary_emotion,
        "topics": sorted(
            [{"id": str(link.topic_id), "name": link.topic.name, "sentiment": link.sentiment, "assigned_by": link.assigned_by} for link in r.topic_links],
            key=lambda t: t["name"],
        ),
        "tags": sorted([{"id": str(t.id), "name": t.name} for t in r.tags], key=lambda t: t["name"]),
        "processing_status": r.processing_status,
        "ai_status": r.ai_status,
        "needs_review": r.needs_review,
        "is_archived": r.is_archived,
        "is_demo": r.is_demo,
        "external_id": r.external_id,
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
    }


def topic_out(t: Topic, stats: dict | None = None) -> dict:
    return {
        "id": str(t.id),
        "name": t.name,
        "description": t.description,
        "keywords": t.keywords or [],
        "origin": t.origin,
        "review_status": t.review_status,
        "is_active": t.is_active,
        "merged_into_id": str(t.merged_into_id) if t.merged_into_id else None,
        "created_at": iso(t.created_at),
        "stats": stats,
    }


def import_out(j: ImportJob) -> dict:
    return {
        "id": str(j.id),
        "file_name": j.file_name,
        "file_type": j.file_type,
        "file_size": j.file_size,
        "encoding": j.encoding,
        "sheet_name": j.sheet_name,
        "columns": j.columns,
        "mapping": j.mapping,
        "options": j.options,
        "status": j.status,
        "total_rows": j.total_rows,
        "valid_rows": j.valid_rows,
        "invalid_rows": j.invalid_rows,
        "duplicate_rows": j.duplicate_rows,
        "imported_rows": j.imported_rows,
        "error_message": j.error_message,
        "job_id": str(j.job_id) if j.job_id else None,
        "created_at": iso(j.created_at),
        "completed_at": iso(j.completed_at),
    }


def job_out(j: Job) -> dict:
    return {
        "id": str(j.id),
        "job_type": j.job_type,
        "status": j.status,
        "progress": j.progress,
        "attempts": j.attempts,
        "max_attempts": j.max_attempts,
        "result": j.result,
        "error": j.error,
        "created_at": iso(j.created_at),
        "started_at": iso(j.started_at),
        "finished_at": iso(j.finished_at),
    }


def insight_out(i: Insight, topic_name: str | None = None, product_name: str | None = None, evidence: list | None = None) -> dict:
    return {
        "id": str(i.id),
        "kind": i.kind,
        "title": i.title,
        "description": i.description,
        "topic": {"id": str(i.topic_id), "name": topic_name} if i.topic_id else None,
        "product": {"id": str(i.product_id), "name": product_name} if i.product_id else None,
        "supporting_count": i.supporting_count,
        "period_start": iso(i.period_start),
        "period_end": iso(i.period_end),
        "trend_direction": i.trend_direction,
        "importance": i.importance,
        "evidence_strength": i.evidence_strength,
        "suggested_action": i.suggested_action,
        "statistics": i.statistics,
        "generated_by": i.generated_by,
        "ai_summary": i.ai_summary,
        "ai_suggested_action": i.ai_suggested_action,
        "ai_provider": i.ai_provider,
        "ai_model": i.ai_model,
        "status": i.status,
        "created_at": iso(i.created_at),
        "evidence": evidence,
    }


def rule_out(r: AlertRule) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "alert_type": r.alert_type,
        "threshold": r.threshold,
        "window_days": r.window_days,
        "min_count": r.min_count,
        "product_id": str(r.product_id) if r.product_id else None,
        "topic_id": str(r.topic_id) if r.topic_id else None,
        "is_enabled": r.is_enabled,
        "cooldown_hours": r.cooldown_hours,
        "last_evaluated_at": iso(r.last_evaluated_at),
        "last_triggered_at": iso(r.last_triggered_at),
        "created_at": iso(r.created_at),
    }


def event_out(e: AlertEvent) -> dict:
    return {
        "id": str(e.id),
        "rule_id": str(e.rule_id) if e.rule_id else None,
        "alert_type": e.alert_type,
        "title": e.title,
        "explanation": e.explanation,
        "severity": e.severity,
        "metrics": e.metrics,
        "evidence_ids": e.evidence_ids,
        "window_start": iso(e.window_start),
        "window_end": iso(e.window_end),
        "status": e.status,
        "is_read": e.is_read,
        "triggered_at": iso(e.triggered_at),
    }


def report_out(r: Report) -> dict:
    return {
        "id": str(r.id),
        "title": r.title,
        "format": r.format,
        "status": r.status,
        "parameters": r.parameters,
        "file_name": r.file_name,
        "size_bytes": r.size_bytes,
        "record_count": r.record_count,
        "includes_ai": r.includes_ai,
        "error": r.error,
        "job_id": str(r.job_id) if r.job_id else None,
        "created_at": iso(r.created_at),
        "completed_at": iso(r.completed_at),
    }
