"""Analysis results, insights, alerts, reports, AI conversations and usage."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, Column, Float, ForeignKey, Index, Integer, LargeBinary, String, Table, Text
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.db.base import Base, UTCDateTime, UUIDMixin, utcnow

if TYPE_CHECKING:
    from app.models.feedback import FeedbackRecord


class SentimentAnalysis(UUIDMixin, Base):
    """Every classification ever made for a record. Manual corrections are appended, never overwrite."""

    __tablename__ = "sentiment_analyses"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feedback_records.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(20))  # lexicon | ai | manual
    label: Mapped[str] = mapped_column(String(20))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)  # -1 .. 1
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0 .. 1 (model-reported, not a guarantee)
    explanation: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    previous_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    # Declared so the unit of work inserts the feedback row first when both are pending.
    feedback: Mapped[FeedbackRecord] = relationship(lazy="raise_on_sql", viewonly=False)


class EmotionAnalysis(UUIDMixin, Base):
    __tablename__ = "emotion_analyses"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feedback_records.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(20))  # keyword | ai
    emotions: Mapped[list] = mapped_column(JSON, default=list)  # [{emotion, confidence, evidence}]
    primary_emotion: Mapped[str | None] = mapped_column(String(30), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    # Declared so the unit of work inserts the feedback row first when both are pending.
    feedback: Mapped[FeedbackRecord] = relationship(lazy="raise_on_sql", viewonly=False)


insight_evidence = Table(
    "insight_evidence",
    Base.metadata,
    Column("insight_id", ForeignKey("insights.id", ondelete="CASCADE"), primary_key=True),
    Column("feedback_id", ForeignKey("feedback_records.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Insight(UUIDMixin, Base):
    __tablename__ = "insights"
    __table_args__ = (Index("ix_insights_ws_status", "workspace_id", "status"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))  # recurring_issue | rising_negative | positive_driver | product_hotspot | emerging_topic
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    supporting_count: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    trend_direction: Mapped[str] = mapped_column(String(20), default="insufficient_data")  # up | down | flat | insufficient_data
    importance: Mapped[str] = mapped_column(String(10), default="medium")  # high | medium | low
    evidence_strength: Mapped[str] = mapped_column(String(10), default="limited")  # strong | moderate | limited
    suggested_action: Mapped[str] = mapped_column(Text, default="")
    statistics: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_by: Mapped[str] = mapped_column(String(10), default="rules")  # rules (deterministic) | ai (AI-written narrative)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_suggested_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | dismissed | resolved
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AlertRule(UUIDMixin, Base):
    __tablename__ = "alert_rules"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    alert_type: Mapped[str] = mapped_column(String(40))
    threshold: Mapped[float] = mapped_column(Float, default=50.0)
    window_days: Mapped[int] = mapped_column(Integer, default=7)
    min_count: Mapped[int] = mapped_column(Integer, default=5)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_hours: Mapped[int] = mapped_column(Integer, default=24)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AlertEvent(UUIDMixin, Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_ws_triggered", "workspace_id", "triggered_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    alert_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    explanation: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    window_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | acknowledged | resolved
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Report(UUIDMixin, Base):
    __tablename__ = "reports"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    format: Mapped[str] = mapped_column(String(10))  # pdf | docx | xlsx | csv
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | ready | failed
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    file_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Stored in the database so generated reports survive restarts on platforms with ephemeral disks.
    content: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    includes_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AIConversation(UUIDMixin, Base):
    __tablename__ = "ai_conversations"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class AIMessage(UUIDMixin, Base):
    __tablename__ = "ai_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)  # feedback record ids
    facts: Mapped[dict] = mapped_column(JSON, default=dict)  # deterministic figures the answer is based on
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AIUsage(UUIDMixin, Base):
    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_ws_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    feature: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
