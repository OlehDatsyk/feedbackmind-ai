"""Reports and exports (PDF, DOCX, XLSX, CSV)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, ReadCtx, require
from app.models import Report
from app.services import jobs
from app.services.feedback import owned
from app.services.filters import FeedbackFilter
from app.services.reports import FORMATS
from app.services.serialize import report_out

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportIn(BaseModel):
    title: str = Field(default="Customer feedback report", min_length=1, max_length=300)
    format: str = Field(pattern="^(pdf|docx|xlsx|csv)$")
    filters: FeedbackFilter = Field(default_factory=FeedbackFilter)


@router.get("")
def list_reports(ctx: ReadCtx, db: DB) -> list[dict]:
    return [report_out(r) for r in db.scalars(select(Report).where(Report.workspace_id == ctx.workspace_id).order_by(Report.created_at.desc()).limit(100))]


@router.post("", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require("reports:create"))])
def create_report(body: ReportIn, ctx: ReadCtx, db: DB) -> dict:
    r = Report(
        workspace_id=ctx.workspace_id,
        title=body.title.strip(),
        format=body.format,
        status="queued",
        parameters={"filters": body.filters.model_dump(mode="json")},
        created_by_id=ctx.user.id,
    )
    db.add(r)
    db.flush()
    job = jobs.enqueue(db, "report_generate", ctx.workspace_id, {"report_id": str(r.id)}, ctx.user.id)
    r.job_id = job.id
    db.commit()
    return report_out(r)


@router.get("/{report_id}")
def get_report(report_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict:
    return report_out(owned(db, Report, ctx.workspace_id, report_id, "Report"))


@router.get("/{report_id}/download")
def download(report_id: uuid.UUID, ctx: ReadCtx, db: DB) -> Response:
    ctx.require("reports:read")
    r = owned(db, Report, ctx.workspace_id, report_id, "Report")
    if r.status != "ready" or r.content is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The report is not ready yet.")
    return Response(content=r.content, media_type=FORMATS[r.format], headers={"Content-Disposition": f'attachment; filename="{r.file_name}"'})


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require("reports:create"))])
def delete_report(report_id: uuid.UUID, ctx: ReadCtx, db: DB) -> Response:
    r = owned(db, Report, ctx.workspace_id, report_id, "Report")
    db.delete(r)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
