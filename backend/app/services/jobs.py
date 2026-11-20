"""Durable database-backed job queue.

Why not Redis/Celery: the workloads (imports, AI batches, reports, alert evaluation) are modest, and keeping jobs in
PostgreSQL means job state survives restarts and needs no extra service. Jobs are claimed with an atomic conditional
UPDATE plus a lease (``locked_until``); a job whose worker died is re-claimed after the lease expires, up to
``max_attempts``. The same worker loop runs either inside the API process (``EMBEDDED_WORKER=true``) or as a separate
process (``python -m app.worker``).
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models import Job

logger = logging.getLogger("feedbackmind.jobs")

Handler = Callable[[Session, Job], dict]
_HANDLERS: dict[str, Handler] = {}
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


class PermanentJobError(Exception):
    """Raise from a handler for failures that retrying cannot fix (bad input, missing configuration)."""


def handler(job_type: str):
    def _register(fn: Handler) -> Handler:
        _HANDLERS[job_type] = fn
        return fn

    return _register


def enqueue(db: Session, job_type: str, workspace_id: uuid.UUID | None, payload: dict, user_id: uuid.UUID | None = None, max_attempts: int = 3) -> Job:
    job = Job(
        job_type=job_type, workspace_id=workspace_id, payload=payload, created_by_id=user_id, max_attempts=max_attempts, status="queued", run_after=utcnow()
    )
    db.add(job)
    db.flush()
    _wake.set()
    return job


def _claim(db: Session) -> Job | None:
    now = utcnow()
    lease = timedelta(seconds=get_settings().job_lease_seconds)
    candidates = db.scalars(
        select(Job.id)
        .where(
            or_(
                and_(Job.status == "queued", Job.run_after <= now),
                and_(Job.status == "running", Job.locked_until < now),  # lease expired: worker died
            )
        )
        .order_by(Job.created_at)
        .limit(5)
    ).all()
    for job_id in candidates:
        res = db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                or_(and_(Job.status == "queued", Job.run_after <= now), and_(Job.status == "running", Job.locked_until < now)),
            )
            .values(status="running", locked_by=WORKER_ID, locked_until=now + lease, started_at=now, attempts=Job.attempts + 1)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        if res.rowcount == 1:
            return db.get(Job, job_id, populate_existing=True)
    return None


def _finish(job_id: uuid.UUID, status: str, result: dict | None = None, error: str | None = None, retry: bool = False) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        if retry and job.attempts < job.max_attempts:
            job.status = "queued"
            job.run_after = utcnow() + timedelta(seconds=min(300, 15 * 2 ** (job.attempts - 1)))
            job.error = error
        else:
            job.status = status
            job.finished_at = utcnow()
            job.error = error
            if result is not None:
                job.result = result
            job.progress = 100 if status == "succeeded" else job.progress
        job.locked_by = None
        job.locked_until = None
        db.commit()
        if job.status == "failed":
            _on_failure(db, job)


_FAILURE_HOOKS: dict[str, Callable[[Session, Job], None]] = {}


def on_failure(job_type: str):
    def _register(fn: Callable[[Session, Job], None]):
        _FAILURE_HOOKS[job_type] = fn
        return fn

    return _register


def _on_failure(db: Session, job: Job) -> None:
    hook = _FAILURE_HOOKS.get(job.job_type)
    if hook:
        try:
            hook(db, job)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Failure hook for job %s raised", job.id)


def run_one() -> bool:
    """Claim and run a single job. Returns False when the queue is empty."""
    _import_handlers()
    with SessionLocal() as db:
        job = _claim(db)
        if job is None:
            return False
        fn = _HANDLERS.get(job.job_type)
        if fn is None:
            _finish(job.id, "failed", error=f"Unknown job type {job.job_type!r}.")
            return True
        logger.info("Running job %s (%s), attempt %s", job.id, job.job_type, job.attempts)
        try:
            result = fn(db, job)
            db.commit()
        except PermanentJobError as exc:
            db.rollback()
            _finish(job.id, "failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - job isolation; error recorded and retried
            db.rollback()
            logger.error("Job %s failed: %s\n%s", job.id, type(exc).__name__, traceback.format_exc(limit=5))
            _finish(job.id, "failed", error=f"{type(exc).__name__}: processing failed.", retry=True)
        else:
            _finish(job.id, "succeeded", result=result or {})
    return True


def run_pending_jobs(limit: int = 100) -> int:
    """Run queued jobs synchronously (used by tests and the CLI)."""
    n = 0
    while n < limit and run_one():
        n += 1
    return n


def set_progress(db: Session, job: Job, progress: int) -> None:
    job.progress = max(0, min(99, progress))
    job.locked_until = utcnow() + timedelta(seconds=get_settings().job_lease_seconds)
    db.commit()


# ------------------------------------------------------------------ worker loop

_wake = threading.Event()
_stop = threading.Event()
_last_alert_scan = 0.0


def _maybe_schedule_alert_scan() -> None:
    global _last_alert_scan
    interval = get_settings().alert_eval_interval_minutes * 60
    if interval <= 0 or time.monotonic() - _last_alert_scan < interval:
        return
    _last_alert_scan = time.monotonic()
    try:
        from app.services.alerts import schedule_periodic_evaluation

        with SessionLocal() as db:
            schedule_periodic_evaluation(db)
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Could not schedule periodic alert evaluation.")


def worker_loop(stop: threading.Event | None = None) -> None:
    stop = stop or _stop
    poll = get_settings().worker_poll_seconds
    logger.info("Job worker %s started.", WORKER_ID)
    while not stop.is_set():
        try:
            _maybe_schedule_alert_scan()
            worked = run_one()
        except Exception:  # noqa: BLE001 - e.g. database temporarily unavailable
            logger.warning("Job worker iteration failed; retrying shortly.", exc_info=True)
            worked = False
        if not worked:
            _wake.wait(poll)
            _wake.clear()
    logger.info("Job worker %s stopped.", WORKER_ID)


_threads: list[threading.Thread] = []


def start_embedded_workers() -> None:
    if _threads:
        return
    _stop.clear()
    for i in range(max(1, get_settings().worker_concurrency)):
        t = threading.Thread(target=worker_loop, name=f"job-worker-{i}", daemon=True)
        t.start()
        _threads.append(t)


def stop_embedded_workers() -> None:
    _stop.set()
    _wake.set()
    for t in _threads:
        t.join(timeout=5)
    _threads.clear()


def _import_handlers() -> None:
    # Handlers register themselves on import.
    from app.services import ai_analysis, alerts, imports, insights, reports, topic_ops  # noqa: F401
