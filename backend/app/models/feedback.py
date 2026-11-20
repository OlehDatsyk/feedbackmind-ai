"""Feedback records and their catalogue (products, sources, tags, topics, notes)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, Float, ForeignKey, Index, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UTCDateTime, UUIDMixin, utcnow

SENTIMENT_LABELS = ("positive", "negative", "neutral", "mixed", "uncertain")
SOURCE_KINDS = ("manual", "import", "api", "webhook", "review", "survey", "support", "social", "internal", "demo", "other")


class Product(UUIDMixin, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_products_workspace_name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class FeedbackSource(UUIDMixin, Base):
    __tablename__ = "feedback_sources"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_feedback_sources_workspace_name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="other")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


feedback_tags = Table(
    "feedback_tags",
    Base.metadata,
    Column("feedback_id", ForeignKey("feedback_records.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Tag(UUIDMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_tags_workspace_name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class FeedbackRecord(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "feedback_records"
    __table_args__ = (
        Index("ix_feedback_ws_received", "workspace_id", "received_at"),
        Index("ix_feedback_ws_sentiment", "workspace_id", "sentiment_label"),
        Index("ix_feedback_ws_hash", "workspace_id", "content_hash"),
        Index("ix_feedback_ws_product", "workspace_id", "product_id"),
        Index("ix_feedback_ws_source", "workspace_id", "source_id"),
        Index("ix_feedback_ws_archived", "workspace_id", "is_archived"),
        Index("ix_feedback_ws_external", "workspace_id", "external_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    # The original text is never modified by analysis; edits by users are recorded in the activity log.
    text: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("feedback_sources.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    customer_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_segment: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))

    # Current (latest) classification, denormalised for fast filtering/aggregation.
    # The full history lives in sentiment_analyses (AI, rule-based and manual corrections).
    sentiment_label: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)  # lexicon | ai | manual
    primary_emotion: Mapped[str | None] = mapped_column(String(30), nullable=True)
    processing_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | processed | failed
    ai_status: Mapped[str] = mapped_column(String(20), default="not_requested")  # not_requested | queued | done | failed
    analyzed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_jobs.id", ondelete="SET NULL"), nullable=True)
    integration_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("integration_configs.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    source: Mapped[FeedbackSource | None] = relationship(lazy="joined")
    product: Mapped[Product | None] = relationship(lazy="joined")
    tags: Mapped[list[Tag]] = relationship(secondary=feedback_tags, lazy="selectin")
    topic_links: Mapped[list[FeedbackTopic]] = relationship(back_populates="feedback", cascade="all, delete-orphan", lazy="selectin")


class FeedbackNote(UUIDMixin, Base):
    __tablename__ = "feedback_notes"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feedback_records.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Topic(UUIDMixin, Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_topics_workspace_name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    origin: Mapped[str] = mapped_column(String(20), default="custom")  # default | custom | ai | discovered
    review_status: Mapped[str] = mapped_column(String(20), default="approved")  # approved | pending_review
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class FeedbackTopic(Base):
    __tablename__ = "feedback_topics"

    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feedback_records.id", ondelete="CASCADE"), primary_key=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True, index=True)
    # Aspect-level sentiment: how the customer feels about this topic specifically.
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    assigned_by: Mapped[str] = mapped_column(String(20), default="rule")  # rule | ai | manual
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    feedback: Mapped[FeedbackRecord] = relationship(back_populates="topic_links")
    topic: Mapped[Topic] = relationship(lazy="joined")
