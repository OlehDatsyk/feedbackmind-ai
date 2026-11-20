"""Report generation (PDF, DOCX, XLSX, CSV) from real database records.

Reports are generated in a background job and stored in the database (not on disk), so they survive restarts on
hosts with ephemeral file systems. Every export applies the same filters as the dashboard and only reads the
requesting workspace's data. Cells that could be interpreted as spreadsheet formulas are neutralised.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import FeedbackRecord, Insight, Job, Report, Workspace, insight_evidence
from app.services import jobs
from app.services.activity import log_activity
from app.services.analytics import compare_topic_periods, distribution, load_rows, topic_stats
from app.services.filters import FeedbackFilter, apply_filters
from app.services.insights import default_period
from app.services.textutil import safe_cell, truncate

FORMATS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
}
MAX_EXPORT_ROWS = 100_000

METHODOLOGY = [
    "All figures are computed from feedback records stored in this workspace that match the report filters (archived records excluded unless requested).",
    "Sentiment percentages are shares of classified records; unclassified records are reported separately.",
    "Sentiment labels come from three methods, shown per record: 'lexicon' (rule-based VADER, English only, not AI), 'ai' (language model) and 'manual' (human correction).",
    "Topic counts use keyword rules, AI topic extraction and manual assignment; a record can belong to several topics.",
    "Emerging problems compare the report period with the preceding period of equal length using a two-proportion z-test (alpha 0.05) and a minimum sample size.",
    "Insights are produced by deterministic rules over the data; AI, when enabled, only writes narrative summaries and is labelled 'AI-generated'.",
    "Limitations: model and lexicon classifications can be wrong (sarcasm, domain language, other languages); small samples are flagged; correlations do not establish causes.",
]


def build_report_data(db: Session, workspace_id: uuid.UUID, f: FeedbackFilter, tz_name: str, include_records: bool) -> dict:
    ws = db.get(Workspace, workspace_id)
    rows = load_rows(db, workspace_id, f, tz_name)
    dist = distribution(rows)
    topics = topic_stats(db, workspace_id, f, tz_name, limit=15)
    d_from, d_to = f.date_from, f.date_to
    if d_from is None or d_to is None:
        d_from, d_to = default_period(db, workspace_id, tz_name)
        emerging_note = f"No date range was selected; emerging problems compare {d_from} to {d_to} with the preceding 30 days."
    else:
        emerging_note = f"Compares {d_from} to {d_to} with the preceding period of equal length."
    changes = compare_topic_periods(db, workspace_id, f.model_copy(update={"date_from": None, "date_to": None}), tz_name, d_from, d_to)
    emerging = [
        c for c in changes if c["is_new"] or (c["negative_share_test"] and c["negative_share_test"]["significant"] and c["negative_share_test"]["diff"] > 0)
    ]
    FR = FeedbackRecord
    pos_stmt = (
        apply_filters(select(FR), workspace_id, f, tz_name)
        .where(FR.sentiment_label == "positive")
        .order_by(FR.sentiment_score.desc().nulls_last(), FR.received_at.desc())
        .limit(5)
    )
    highlights = [
        {"id": str(r.id), "date": r.received_at.date().isoformat(), "text": truncate(r.text, 400), "method": r.sentiment_method}
        for r in db.scalars(pos_stmt).unique()
    ]
    insights = []
    for ins in db.scalars(
        select(Insight).where(Insight.workspace_id == workspace_id, Insight.status == "active").order_by(Insight.created_at.desc()).limit(15)
    ):
        ev = db.execute(
            select(FR.id, FR.text).join(insight_evidence, insight_evidence.c.feedback_id == FR.id).where(insight_evidence.c.insight_id == ins.id).limit(3)
        ).all()
        insights.append(
            {
                "title": ins.title,
                "description": ins.description,
                "importance": ins.importance,
                "supporting_count": ins.supporting_count,
                "evidence_strength": ins.evidence_strength,
                "trend": ins.trend_direction,
                "suggested_action": ins.suggested_action,
                "ai_summary": ins.ai_summary,
                "ai_suggested_action": ins.ai_suggested_action,
                "ai_model": ins.ai_model,
                "evidence": [{"id": str(i), "text": truncate(t, 300)} for i, t in ev],
            }
        )
    data = {
        "workspace": ws.name if ws else "",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "date_range": f"{f.date_from or 'earliest'} to {f.date_to or 'latest'}",
        "filters": f.describe(),
        "distribution": dist,
        "topics": topics,
        "emerging": emerging[:10],
        "emerging_note": emerging_note,
        "highlights": highlights,
        "insights": insights,
        "includes_ai": any(i["ai_summary"] for i in insights),
        "methodology": METHODOLOGY,
    }
    if include_records:
        stmt = apply_filters(select(FR), workspace_id, f, tz_name).order_by(FR.received_at.desc()).limit(MAX_EXPORT_ROWS)
        data["records"] = [
            {
                "id": str(r.id),
                "received_at": r.received_at.isoformat(),
                "text": r.text,
                "title": r.title or "",
                "source": r.source.name if r.source else "",
                "product": r.product.name if r.product else "",
                "customer_ref": r.customer_ref or "",
                "segment": r.customer_segment or "",
                "language": r.language or "",
                "rating": r.rating if r.rating is not None else "",
                "sentiment": r.sentiment_label or "",
                "sentiment_score": r.sentiment_score if r.sentiment_score is not None else "",
                "sentiment_confidence": r.sentiment_confidence if r.sentiment_confidence is not None else "",
                "classification_method": r.sentiment_method or "",
                "primary_emotion": r.primary_emotion or "",
                "topics": ", ".join(sorted(link.topic.name for link in r.topic_links)),
                "tags": ", ".join(sorted(t.name for t in r.tags)),
                "needs_review": r.needs_review,
                "archived": r.is_archived,
                "demo_data": r.is_demo,
            }
            for r in db.scalars(stmt).unique()
        ]
    return data


RECORD_COLUMNS = [
    "id",
    "received_at",
    "text",
    "title",
    "source",
    "product",
    "customer_ref",
    "segment",
    "language",
    "rating",
    "sentiment",
    "sentiment_score",
    "sentiment_confidence",
    "classification_method",
    "primary_emotion",
    "topics",
    "tags",
    "needs_review",
    "archived",
    "demo_data",
]


def render_csv(data: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(RECORD_COLUMNS)
    for r in data.get("records", []):
        w.writerow([safe_cell(r[c]) for c in RECORD_COLUMNS])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def render_xlsx(data: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    bold = Font(bold=True)
    d = data["distribution"]
    rows = [
        ("FeedbackMind AI report", ""),
        ("Workspace", data["workspace"]),
        ("Generated", data["generated_at"]),
        ("Date range", data["date_range"]),
        ("Records", d["total"]),
        ("Classified records", d["classified"]),
        ("Average sentiment score (-1..1)", d["average_score"] if d["average_score"] is not None else "n/a"),
        ("", ""),
        ("Sentiment", "Count / % of classified"),
    ]
    rows += [(k, f"{d['counts'][k]} ({d['percentages'][k] if d['percentages'][k] is not None else 'n/a'}%)") for k in d["counts"]]
    for r in rows:
        ws.append([safe_cell(x) for x in r])
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 30

    t = wb.create_sheet("Topics")
    t.append(["Topic", "Records", "Positive", "Negative", "Neutral", "Mixed", "Negative share %", "Small sample"])
    for c in t[1]:
        c.font = bold
    for x in data["topics"]:
        t.append(
            [safe_cell(x["name"]), x["count"], x["positive"], x["negative"], x["neutral"], x["mixed"], x["negative_share"], "yes" if x["low_sample"] else "no"]
        )

    i = wb.create_sheet("Insights")
    i.append(
        ["Title", "Importance", "Supporting records", "Evidence strength", "Rule-based suggestion", "AI-generated summary", "AI-generated suggested action"]
    )
    for c in i[1]:
        c.font = bold
    for x in data["insights"]:
        i.append(
            [
                safe_cell(x["title"]),
                x["importance"],
                x["supporting_count"],
                x["evidence_strength"],
                safe_cell(x["suggested_action"]),
                safe_cell(x["ai_summary"] or ""),
                safe_cell(x["ai_suggested_action"] or ""),
            ]
        )

    if "records" in data:
        r = wb.create_sheet("Records")
        r.append(RECORD_COLUMNS)
        for c in r[1]:
            c.font = bold
        for rec in data["records"]:
            r.append([safe_cell(rec[c]) for c in RECORD_COLUMNS])

    m = wb.create_sheet("Methodology")
    for line in data["methodology"]:
        m.append([line])
    m.column_dimensions["A"].width = 140
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _sections(data: dict) -> list[tuple[str, list]]:
    """Format-neutral content: list of (heading, items). Items are ('p', text) | ('bullet', text) | ('table', rows)."""
    d = data["distribution"]
    s: list[tuple[str, list]] = []
    s.append(
        (
            "Overview",
            [
                ("p", f"Workspace: {data['workspace']}"),
                ("p", f"Report date: {data['generated_at']}"),
                ("p", f"Date range: {data['date_range']}"),
                ("p", f"Feedback volume: {d['total']} records ({d['classified']} classified, {d['unclassified']} unclassified)."),
                (
                    "p",
                    f"Average sentiment score: {d['average_score']:+.2f} on a -1 to +1 scale ({d['average_score_n']} records with a score)."
                    if d["average_score"] is not None
                    else "Average sentiment score: not available.",
                ),
            ],
        )
    )
    s.append(
        (
            "Sentiment distribution",
            [
                (
                    "table",
                    [["Sentiment", "Records", "% of classified"]]
                    + [[k.title(), str(d["counts"][k]), f"{d['percentages'][k]}%" if d["percentages"][k] is not None else "n/a"] for k in d["counts"]],
                )
            ],
        )
    )
    s.append(
        (
            "Main topics",
            [
                (
                    "table",
                    [["Topic", "Records", "Negative", "Positive", "Negative %"]]
                    + [
                        [
                            t["name"] + (" *" if t["low_sample"] else ""),
                            str(t["count"]),
                            str(t["negative"]),
                            str(t["positive"]),
                            f"{t['negative_share']}%" if t["negative_share"] is not None else "n/a",
                        ]
                        for t in data["topics"]
                    ],
                )
            ]
            + [("p", "* Small sample - treat as anecdotal.")]
            if data["topics"]
            else [("p", "No topics assigned in this range.")],
        )
    )
    em = [("p", data["emerging_note"])]
    em += [
        (
            "bullet",
            f"{c['name']}: {c['current_count']} records (previous {c['previous_count']}); negative share {c['previous_negative_share']}% → {c['current_negative_share']}%"
            + (" — new topic" if c["is_new"] else ""),
        )
        for c in data["emerging"]
    ] or [("p", "No statistically supported emerging problems.")]
    s.append(("Emerging problems", em))
    s.append(
        (
            "Positive feedback highlights",
            [("bullet", f'"{h["text"]}" ({h["date"]}, classified by {h["method"]})') for h in data["highlights"]]
            or [("p", "No positive records in this range.")],
        )
    )
    ins_items: list = []
    for x in data["insights"]:
        ins_items.append(
            (
                "bullet",
                f"[{x['importance'].upper()}] {x['title']} — {x['description']} ({x['supporting_count']} supporting records, evidence {x['evidence_strength']})",
            )
        )
        if x["ai_summary"]:
            ins_items.append(("p", f"AI-generated summary ({x['ai_model']}): {x['ai_summary']}"))
        for e in x["evidence"]:
            ins_items.append(("p", f'Evidence [{e["id"][:8]}]: "{e["text"]}"'))
    s.append(("Insights and supporting evidence", ins_items or [("p", "No active insights. Generate insights on the Insights page.")]))
    acts: list = []
    for x in data["insights"]:
        acts.append(("bullet", f"{x['title']}: {x['suggested_action']} (rule-based suggestion)"))
        if x["ai_suggested_action"]:
            acts.append(("bullet", f"{x['title']}: {x['ai_suggested_action']} (AI-generated)"))
    s.append(("Recommended actions", acts or [("p", "No recommendations without insights.")]))
    s.append(("Methodology and limitations", [("bullet", m) for m in data["methodology"]]))
    return s


def render_pdf(data: dict) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title="FeedbackMind AI report")
    st = getSampleStyleSheet()
    story = [Paragraph("FeedbackMind AI — Customer Feedback Report", st["Title"])]
    for heading, items in _sections(data):
        story.append(Paragraph(escape(heading), st["Heading2"]))
        for kind, val in items:
            if kind == "table":
                tbl = Table([[Paragraph(escape(str(c)), st["BodyText"]) for c in row] for row in val], repeatRows=1)
                tbl.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f1f3d")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    )
                )
                story.append(tbl)
            elif kind == "bullet":
                story.append(Paragraph("• " + escape(val), st["BodyText"]))
            else:
                story.append(Paragraph(escape(val), st["BodyText"]))
        story.append(Spacer(1, 4 * mm))
    doc.build(story)
    return buf.getvalue()


def render_docx(data: dict) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("FeedbackMind AI — Customer Feedback Report", 0)
    for heading, items in _sections(data):
        doc.add_heading(heading, level=1)
        for kind, val in items:
            if kind == "table":
                table = doc.add_table(rows=0, cols=len(val[0]))
                table.style = "Light Grid Accent 1"
                for row in val:
                    cells = table.add_row().cells
                    for i, c in enumerate(row):
                        cells[i].text = str(c)
            elif kind == "bullet":
                doc.add_paragraph(val, style="List Bullet")
            else:
                doc.add_paragraph(val)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


RENDERERS = {"pdf": render_pdf, "docx": render_docx, "xlsx": render_xlsx, "csv": render_csv}


@jobs.handler("report_generate")
def generate_report(db: Session, job: Job) -> dict:
    report = db.get(Report, uuid.UUID(job.payload["report_id"]))
    if report is None:
        raise jobs.PermanentJobError("Report no longer exists.")
    ws = db.get(Workspace, report.workspace_id)
    report.status = "running"
    params = report.parameters or {}
    f = FeedbackFilter.model_validate(params.get("filters") or {})
    include_records = report.format in ("csv", "xlsx")
    data = build_report_data(db, report.workspace_id, f, ws.timezone if ws else "UTC", include_records)
    content = RENDERERS[report.format](data)
    ext = report.format
    stamp = utcnow().strftime("%Y%m%d-%H%M")
    report.file_name = f"feedbackmind-report-{stamp}.{ext}"
    report.content = content
    report.size_bytes = len(content)
    report.record_count = data["distribution"]["total"]
    report.includes_ai = data["includes_ai"]
    report.status = "ready"
    report.completed_at = utcnow()
    log_activity(db, report.workspace_id, report.created_by_id, "report.generated", f"Generated {ext.upper()} report", "report", report.id)
    return {"report_id": str(report.id), "size": len(content)}


@jobs.on_failure("report_generate")
def _report_failed(db: Session, job: Job) -> None:
    report = db.get(Report, uuid.UUID(job.payload["report_id"]))
    if report is not None:
        report.status = "failed"
        report.error = job.error or "Report generation failed."
