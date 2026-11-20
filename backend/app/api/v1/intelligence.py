"""Insights, alerts, comparisons and the AI Business Analyst."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.ai.service import require_ai
from app.api.deps import DB, ReadCtx, require
from app.core.ratelimit import ai_rate_limit
from app.db.base import utcnow
from app.models import AIConversation, AIMessage, AlertEvent, AlertRule, FeedbackRecord, Insight, Product, Topic, insight_evidence
from app.services import jobs
from app.services.activity import log_activity
from app.services.alerts import ALERT_TYPES, evaluate_workspace
from app.services.assistant import answer
from app.services.comparisons import Segment, compare
from app.services.feedback import owned
from app.services.insights import generate_insights
from app.services.serialize import event_out, feedback_summary, insight_out, iso, job_out, rule_out

router = APIRouter(tags=["intelligence"])


# ------------------------------------------------------------------------------------ insights


class GenerateIn(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    with_ai_narrative: bool = False


class InsightStatusIn(BaseModel):
    status: str = Field(pattern="^(active|dismissed|resolved)$")


def _names(db, ws_id) -> tuple[dict, dict]:
    topics = {t.id: t.name for t in db.scalars(select(Topic).where(Topic.workspace_id == ws_id))}
    products = {p.id: p.name for p in db.scalars(select(Product).where(Product.workspace_id == ws_id))}
    return topics, products


@router.get("/insights")
def list_insights(ctx: ReadCtx, db: DB, status_: str = Query("active", alias="status", pattern="^(active|dismissed|resolved|all)$")) -> list[dict]:
    stmt = select(Insight).where(Insight.workspace_id == ctx.workspace_id)
    if status_ != "all":
        stmt = stmt.where(Insight.status == status_)
    topics, products = _names(db, ctx.workspace_id)
    order = {"high": 0, "medium": 1, "low": 2}
    items = [insight_out(i, topics.get(i.topic_id), products.get(i.product_id)) for i in db.scalars(stmt.order_by(Insight.created_at.desc()).limit(200))]
    items.sort(key=lambda i: (order.get(i["importance"], 3), -i["supporting_count"]))
    return items


@router.post("/insights/generate", dependencies=[Depends(require("insights:manage"))])
def generate(body: GenerateIn, ctx: ReadCtx, db: DB) -> dict:
    if (body.date_from is None) != (body.date_to is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Provide both date_from and date_to, or neither.")
    if body.date_from and body.date_to and body.date_from > body.date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "date_from must be before date_to.")
    if body.with_ai_narrative:
        try:
            require_ai(db, ctx.workspace_id)
        except Exception as exc:  # noqa: BLE001 - AIError subclasses
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    created = generate_insights(db, ctx.workspace_id, ctx.workspace.timezone, ctx.user.id, body.date_from, body.date_to)
    job = None
    if body.with_ai_narrative and created:
        job = jobs.enqueue(db, "insights_narrate", ctx.workspace_id, {"insight_ids": [str(i.id) for i in created]}, ctx.user.id, max_attempts=2)
    db.commit()
    topics, products = _names(db, ctx.workspace_id)
    return {"insights": [insight_out(i, topics.get(i.topic_id), products.get(i.product_id)) for i in created], "narrative_job": job_out(job) if job else None}


@router.get("/insights/{insight_id}")
def get_insight(insight_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict:
    ins = owned(db, Insight, ctx.workspace_id, insight_id, "Insight")
    topics, products = _names(db, ctx.workspace_id)
    ev = db.scalars(
        select(FeedbackRecord)
        .join(insight_evidence, insight_evidence.c.feedback_id == FeedbackRecord.id)
        .where(insight_evidence.c.insight_id == ins.id, FeedbackRecord.workspace_id == ctx.workspace_id)
    ).unique()
    return insight_out(ins, topics.get(ins.topic_id), products.get(ins.product_id), [feedback_summary(r) for r in ev])


@router.patch("/insights/{insight_id}", dependencies=[Depends(require("insights:manage"))])
def set_insight_status(insight_id: uuid.UUID, body: InsightStatusIn, ctx: ReadCtx, db: DB) -> dict:
    ins = owned(db, Insight, ctx.workspace_id, insight_id, "Insight")
    ins.status = body.status
    log_activity(db, ctx.workspace_id, ctx.user.id, "insight.status_changed", f"Insight marked {body.status}", "insight", ins.id)
    db.commit()
    return insight_out(ins)


# ------------------------------------------------------------------------------------ alerts


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    alert_type: str
    threshold: float = Field(ge=0, le=10000)
    window_days: int = Field(default=7, ge=1, le=365)
    min_count: int = Field(default=5, ge=1, le=100000)
    product_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    is_enabled: bool = True
    cooldown_hours: int = Field(default=24, ge=0, le=24 * 90)


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    threshold: float | None = Field(default=None, ge=0, le=10000)
    window_days: int | None = Field(default=None, ge=1, le=365)
    min_count: int | None = Field(default=None, ge=1, le=100000)
    product_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    is_enabled: bool | None = None
    cooldown_hours: int | None = Field(default=None, ge=0, le=24 * 90)


class EventUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|acknowledged|resolved)$")
    is_read: bool | None = None


AlertManage = Depends(require("alerts:manage"))


@router.get("/alerts/types")
def alert_types(ctx: ReadCtx) -> list[dict]:
    return [{"key": k, **v} for k, v in ALERT_TYPES.items()]


@router.get("/alerts/rules")
def list_rules(ctx: ReadCtx, db: DB) -> list[dict]:
    return [rule_out(r) for r in db.scalars(select(AlertRule).where(AlertRule.workspace_id == ctx.workspace_id).order_by(AlertRule.created_at))]


@router.post("/alerts/rules", status_code=status.HTTP_201_CREATED, dependencies=[AlertManage])
def create_rule(body: RuleIn, ctx: ReadCtx, db: DB) -> dict:
    if body.alert_type not in ALERT_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown alert type.")
    if body.alert_type == "product_complaints" and not body.product_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a product for a product-complaints alert.")
    owned(db, Product, ctx.workspace_id, body.product_id, "Product")
    owned(db, Topic, ctx.workspace_id, body.topic_id, "Topic")
    r = AlertRule(workspace_id=ctx.workspace_id, created_by_id=ctx.user.id, **body.model_dump())
    db.add(r)
    log_activity(db, ctx.workspace_id, ctx.user.id, "alert.rule_created", f"Created alert rule {body.name}", "alert_rule", None)
    db.commit()
    return rule_out(r)


@router.patch("/alerts/rules/{rule_id}", dependencies=[AlertManage])
def update_rule(rule_id: uuid.UUID, body: RuleUpdate, ctx: ReadCtx, db: DB) -> dict:
    r = owned(db, AlertRule, ctx.workspace_id, rule_id, "Alert rule")
    data = body.model_dump(exclude_unset=True)
    if "product_id" in data:
        owned(db, Product, ctx.workspace_id, data["product_id"], "Product")
    if "topic_id" in data:
        owned(db, Topic, ctx.workspace_id, data["topic_id"], "Topic")
    for k, v in data.items():
        setattr(r, k, v)
    db.commit()
    return rule_out(r)


@router.delete("/alerts/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[AlertManage])
def delete_rule(rule_id: uuid.UUID, ctx: ReadCtx, db: DB) -> Response:
    r = owned(db, AlertRule, ctx.workspace_id, rule_id, "Alert rule")
    db.delete(r)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/alerts/evaluate", dependencies=[AlertManage])
def evaluate_now(ctx: ReadCtx, db: DB) -> dict:
    events = evaluate_workspace(db, ctx.workspace_id)
    db.commit()
    return {"triggered": [event_out(e) for e in events]}


@router.get("/alerts/events")
def list_events(ctx: ReadCtx, db: DB, status_: str | None = Query(None, alias="status"), limit: int = Query(50, ge=1, le=200)) -> dict:
    stmt = select(AlertEvent).where(AlertEvent.workspace_id == ctx.workspace_id)
    if status_:
        stmt = stmt.where(AlertEvent.status == status_)
    unread = db.scalar(select(func.count(AlertEvent.id)).where(AlertEvent.workspace_id == ctx.workspace_id, AlertEvent.is_read.is_(False))) or 0
    return {"unread": unread, "items": [event_out(e) for e in db.scalars(stmt.order_by(AlertEvent.triggered_at.desc()).limit(limit))]}


@router.patch("/alerts/events/{event_id}")
def update_event(event_id: uuid.UUID, body: EventUpdate, ctx: ReadCtx, db: DB) -> dict:
    e = owned(db, AlertEvent, ctx.workspace_id, event_id, "Alert")
    if body.status is not None:
        ctx.require("alerts:manage")
        e.status = body.status
    if body.is_read is not None:
        e.is_read = body.is_read
    db.commit()
    return event_out(e)


@router.post("/alerts/events/read-all")
def read_all(ctx: ReadCtx, db: DB) -> dict:
    res = db.execute(update(AlertEvent).where(AlertEvent.workspace_id == ctx.workspace_id, AlertEvent.is_read.is_(False)).values(is_read=True))
    db.commit()
    return {"updated": res.rowcount}


# ------------------------------------------------------------------------------------ comparisons


class CompareIn(BaseModel):
    a: Segment
    b: Segment


@router.post("/comparisons")
def run_comparison(body: CompareIn, ctx: ReadCtx, db: DB) -> dict:
    for seg in (body.a, body.b):
        for pid in seg.product_ids:
            owned(db, Product, ctx.workspace_id, pid, "Product")
        if seg.date_from and seg.date_to and seg.date_from > seg.date_to:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A segment's start date is after its end date.")
    return compare(db, ctx.workspace_id, ctx.workspace.timezone, body.a, body.b)


# ------------------------------------------------------------------------------------ AI analyst


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: uuid.UUID | None = None


def _msg_out(m: AIMessage) -> dict:
    return {
        "id": str(m.id),
        "role": m.role,
        "content": m.content,
        "citations": m.citations,
        "facts": m.facts,
        "ai_generated": m.ai_generated,
        "provider": m.provider,
        "model": m.model,
        "created_at": iso(m.created_at),
    }


def _conversation(db, ctx, conversation_id: uuid.UUID) -> AIConversation:
    c = db.get(AIConversation, conversation_id)
    # Conversations are private to the user who created them, within the workspace.
    if c is None or c.workspace_id != ctx.workspace_id or c.user_id != ctx.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return c


@router.get("/assistant/conversations")
def conversations(ctx: ReadCtx, db: DB) -> list[dict]:
    rows = db.scalars(
        select(AIConversation)
        .where(AIConversation.workspace_id == ctx.workspace_id, AIConversation.user_id == ctx.user.id)
        .order_by(AIConversation.updated_at.desc())
        .limit(100)
    )
    return [{"id": str(c.id), "title": c.title, "updated_at": iso(c.updated_at)} for c in rows]


@router.get("/assistant/conversations/{conversation_id}")
def conversation(conversation_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict:
    c = _conversation(db, ctx, conversation_id)
    msgs = db.scalars(select(AIMessage).where(AIMessage.conversation_id == c.id).order_by(AIMessage.created_at))
    return {"id": str(c.id), "title": c.title, "messages": [_msg_out(m) for m in msgs]}


@router.delete("/assistant/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: uuid.UUID, ctx: ReadCtx, db: DB) -> Response:
    c = _conversation(db, ctx, conversation_id)
    db.delete(c)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/assistant/ask", dependencies=[Depends(require("assistant:use")), Depends(ai_rate_limit)])
def ask(body: AskIn, ctx: ReadCtx, db: DB) -> dict:
    if body.conversation_id:
        c = _conversation(db, ctx, body.conversation_id)
    else:
        c = AIConversation(workspace_id=ctx.workspace_id, user_id=ctx.user.id, title=body.question[:120])
        db.add(c)
        db.flush()
    user_msg = AIMessage(conversation_id=c.id, role="user", content=body.question)
    db.add(user_msg)
    db.flush()
    reply = answer(db, ctx.workspace_id, ctx.workspace.timezone, c, body.question)
    db.add(reply)
    c.updated_at = utcnow()
    db.commit()
    return {"conversation_id": str(c.id), "question": _msg_out(user_msg), "answer": _msg_out(reply)}
