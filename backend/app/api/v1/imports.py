"""Guided data import endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, ReadCtx, WriteCtx
from app.core.config import get_settings
from app.models import ImportJob, ImportRowError, Job
from app.services.activity import log_activity
from app.services.feedback import owned
from app.services.imports import FIELDS, SUPPORTED_ENCODINGS, confirm_job, create_upload, load_parsed, rejected_rows_csv, validate_job
from app.services.serialize import import_out, job_out

router = APIRouter(prefix="/imports", tags=["imports"])


class ValidateIn(BaseModel):
    mapping: dict[str, str] = Field(description="application field -> source column")
    options: dict = Field(default_factory=dict)


@router.get("/fields")
def fields(ctx: ReadCtx) -> dict:
    s = get_settings()
    return {
        "fields": [{"key": k, "label": v["label"], "required": v["required"]} for k, v in FIELDS.items()],
        "max_file_mb": s.max_import_mb,
        "max_rows": s.max_import_rows,
        "accepted_types": [".csv", ".xlsx", ".json"],
        "encodings": list(SUPPORTED_ENCODINGS),
    }


@router.get("")
def list_imports(ctx: ReadCtx, db: DB, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    rows = db.scalars(select(ImportJob).where(ImportJob.workspace_id == ctx.workspace_id).order_by(ImportJob.created_at.desc()).limit(limit))
    return [import_out(j) for j in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload(ctx: WriteCtx, db: DB, file: UploadFile = File(...), encoding: str | None = Form(None)) -> dict:
    ctx.require("imports:manage")
    limit = get_settings().max_import_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than the {get_settings().max_import_mb} MB limit.")
    job, parsed = create_upload(db, ctx.workspace_id, ctx.user.id, file.filename or "upload", content, encoding)
    log_activity(db, ctx.workspace_id, ctx.user.id, "import.uploaded", f"Uploaded {job.file_name} ({job.total_rows} rows)", "import", job.id)
    db.commit()
    out = import_out(job)
    out["sample_rows"] = [[("" if v is None else str(v))[:300] for v in row] for row in parsed.rows[:10]]
    return out


@router.get("/{import_id}")
def get_import(import_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict:
    job = owned(db, ImportJob, ctx.workspace_id, import_id, "Import")
    out = import_out(job)
    if job.job_id:
        q = db.get(Job, job.job_id)
        out["job"] = job_out(q) if q else None
    if job.status in ("uploaded", "validated"):
        try:
            parsed = load_parsed(db, job)
            out["sample_rows"] = [[("" if v is None else str(v))[:300] for v in row] for row in parsed.rows[:10]]
        except HTTPException:
            out["sample_rows"] = []
    return out


@router.post("/{import_id}/validate")
def validate(import_id: uuid.UUID, body: ValidateIn, ctx: WriteCtx, db: DB) -> dict:
    ctx.require("imports:manage")
    job = owned(db, ImportJob, ctx.workspace_id, import_id, "Import")
    summary = validate_job(db, job, body.mapping, body.options)
    db.commit()
    return {"import": import_out(job), **summary}


@router.post("/{import_id}/confirm")
def confirm(import_id: uuid.UUID, ctx: WriteCtx, db: DB) -> dict:
    ctx.require("imports:manage")
    job = owned(db, ImportJob, ctx.workspace_id, import_id, "Import")
    q = confirm_job(db, job, ctx.user.id)
    log_activity(db, ctx.workspace_id, ctx.user.id, "import.confirmed", f"Confirmed import of {job.file_name}", "import", job.id)
    db.commit()
    return {"import": import_out(job), "job": job_out(q)}


@router.post("/{import_id}/cancel")
def cancel(import_id: uuid.UUID, ctx: WriteCtx, db: DB) -> dict:
    job = owned(db, ImportJob, ctx.workspace_id, import_id, "Import")
    if job.status not in ("uploaded", "validated"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"An import that is {job.status} cannot be cancelled.")
    job.status = "cancelled"
    job.file_bytes = None
    db.commit()
    return import_out(job)


@router.get("/{import_id}/errors")
def errors(import_id: uuid.UUID, ctx: ReadCtx, db: DB, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)) -> dict:
    job = owned(db, ImportJob, ctx.workspace_id, import_id, "Import")
    total = db.scalar(select(func.count(ImportRowError.id)).where(ImportRowError.import_job_id == job.id)) or 0
    rows = db.scalars(select(ImportRowError).where(ImportRowError.import_job_id == job.id).order_by(ImportRowError.row_number).limit(limit).offset(offset))
    return {"total": total, "items": [{"row_number": e.row_number, "error_type": e.error_type, "message": e.message, "raw": e.raw_data} for e in rows]}


@router.get("/{import_id}/errors.csv")
def errors_csv(import_id: uuid.UUID, ctx: ReadCtx, db: DB) -> Response:
    job = owned(db, ImportJob, ctx.workspace_id, import_id, "Import")
    return Response(
        content=rejected_rows_csv(db, job),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="rejected-rows-{job.id.hex[:8]}.csv"'},
    )
