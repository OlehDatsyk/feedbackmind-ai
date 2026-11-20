"""Applying analysis results to feedback records (baseline, AI and manual corrections)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import EmotionAnalysis, FeedbackRecord, FeedbackTopic, SentimentAnalysis, Topic
from app.services.baseline import (
    DEFAULT_TOPICS,
    LEXICON_VERSION,
    aspect_sentiment,
    keyword_emotions,
    keyword_hits,
    lexicon_sentiment,
)

EMOTIONS = ("frustration", "satisfaction", "confusion", "disappointment", "appreciation", "urgency", "concern", "excitement")


def ensure_default_topics(db: Session, workspace_id: uuid.UUID) -> None:
    existing = {n.casefold() for n in db.scalars(select(Topic.name).where(Topic.workspace_id == workspace_id))}
    for name, description, keywords in DEFAULT_TOPICS:
        if name.casefold() not in existing:
            db.add(Topic(workspace_id=workspace_id, name=name, description=description, keywords=list(keywords), origin="default"))
    db.flush()


def active_topics(db: Session, workspace_id: uuid.UUID) -> list[Topic]:
    return list(
        db.scalars(select(Topic).where(Topic.workspace_id == workspace_id, Topic.is_active.is_(True), Topic.merged_into_id.is_(None)).order_by(Topic.name))
    )


def apply_rule_topics(db: Session, record: FeedbackRecord, topics: Sequence[Topic], is_new: bool = False) -> None:
    """(Re)compute keyword-rule topic links. AI and manual links are left untouched."""
    kept: set[uuid.UUID] = set()
    if not is_new:
        db.execute(delete(FeedbackTopic).where(FeedbackTopic.feedback_id == record.id, FeedbackTopic.assigned_by == "rule"))
        kept = {link.topic_id for link in db.scalars(select(FeedbackTopic).where(FeedbackTopic.feedback_id == record.id))}
    lower = record.text.lower()
    for topic in topics:
        if topic.id in kept or not topic.keywords:
            continue
        hits = keyword_hits(lower, topic.keywords)
        if not hits:
            continue
        sentiment, evidence = aspect_sentiment(record.text, topic.keywords)
        db.add(FeedbackTopic(feedback_id=record.id, topic_id=topic.id, sentiment=sentiment, assigned_by="rule", confidence=None, evidence=evidence))


def apply_baseline(db: Session, record: FeedbackRecord, topics: Sequence[Topic], is_new: bool = False) -> None:
    """Run the deterministic analyser. Never overrides an AI or manual classification."""
    result = lexicon_sentiment(record.text)
    db.add(
        SentimentAnalysis(
            workspace_id=record.workspace_id,
            feedback_id=record.id,
            method="lexicon",
            label=result.label,
            score=result.score,
            confidence=None,
            explanation=result.explanation,
            evidence=result.evidence,
            language=result.language,
            provider="builtin",
            model=LEXICON_VERSION,
        )
    )
    if record.language is None and result.language:
        record.language = result.language
    if record.sentiment_method not in ("ai", "manual"):
        record.sentiment_label = result.label
        record.sentiment_score = result.score
        record.sentiment_confidence = None
        record.sentiment_method = "lexicon"
    emotions = keyword_emotions(record.text)
    db.add(
        EmotionAnalysis(
            workspace_id=record.workspace_id,
            feedback_id=record.id,
            method="keyword",
            emotions=emotions,
            primary_emotion=emotions[0]["emotion"] if emotions else None,
            explanation="Keyword cues only; indicates wording, not a person's emotional state." if emotions else "No emotion keywords found.",
            provider="builtin",
            model=LEXICON_VERSION,
        )
    )
    if record.ai_status != "done":
        record.primary_emotion = emotions[0]["emotion"] if emotions else None
    apply_rule_topics(db, record, topics, is_new=is_new)
    record.processing_status = "processed"
    record.analyzed_at = utcnow()


def correct_sentiment(db: Session, record: FeedbackRecord, label: str, note: str, user_id: uuid.UUID) -> SentimentAnalysis:
    """Manual correction: appended to the history (previous AI/lexicon results are preserved)."""
    analysis = SentimentAnalysis(
        workspace_id=record.workspace_id,
        feedback_id=record.id,
        method="manual",
        label=label,
        score=None,
        confidence=None,
        explanation=note or "Manually corrected.",
        evidence=[],
        language=record.language,
        previous_label=record.sentiment_label,
        created_by_id=user_id,
    )
    db.add(analysis)
    record.sentiment_label = label
    # A numeric score from a different method would no longer match the label; averages exclude manual labels.
    record.sentiment_score = None
    record.sentiment_confidence = None
    record.sentiment_method = "manual"
    return analysis
