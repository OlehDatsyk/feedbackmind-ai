"""Topic management operations: re-applying keyword rules, merging, and statistical topic discovery."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import AlertRule, FeedbackRecord, FeedbackTopic, Insight, Job, Topic
from app.services import jobs
from app.services.analysis import active_topics, apply_rule_topics
from app.services.filters import FeedbackFilter, apply_filters


@jobs.handler("topics_reapply")
def reapply_rules(db: Session, job: Job) -> dict:
    workspace_id = job.workspace_id
    assert workspace_id is not None
    topics = active_topics(db, workspace_id)
    ids = list(db.scalars(select(FeedbackRecord.id).where(FeedbackRecord.workspace_id == workspace_id)))
    for n, rid in enumerate(ids, start=1):
        rec = db.get(FeedbackRecord, rid)
        if rec is not None:
            apply_rule_topics(db, rec, topics)
        if n % 500 == 0:
            db.flush()
            jobs.set_progress(db, job, int(100 * n / len(ids)))
    return {"records": len(ids)}


def merge_topics(db: Session, workspace_id: uuid.UUID, source: Topic, target: Topic) -> int:
    """Move all links from ``source`` to ``target``; keyword lists are combined; source is kept as an alias."""
    moved = 0
    links = list(db.scalars(select(FeedbackTopic).where(FeedbackTopic.topic_id == source.id)))
    existing = set(db.scalars(select(FeedbackTopic.feedback_id).where(FeedbackTopic.topic_id == target.id)))
    for link in links:
        if link.feedback_id in existing:
            db.delete(link)
        else:
            db.add(
                FeedbackTopic(
                    feedback_id=link.feedback_id,
                    topic_id=target.id,
                    sentiment=link.sentiment,
                    assigned_by=link.assigned_by,
                    confidence=link.confidence,
                    evidence=link.evidence,
                )
            )
            db.delete(link)
            moved += 1
    db.flush()
    target.keywords = list(dict.fromkeys([*(target.keywords or []), *(source.keywords or [])]))
    source.is_active = False
    source.merged_into_id = target.id
    db.execute(update(Topic).where(Topic.merged_into_id == source.id).values(merged_into_id=target.id))
    db.execute(update(Insight).where(Insight.topic_id == source.id).values(topic_id=target.id))
    db.execute(update(AlertRule).where(AlertRule.topic_id == source.id).values(topic_id=target.id))
    return moved


def delete_topic(db: Session, topic: Topic) -> None:
    db.execute(delete(FeedbackTopic).where(FeedbackTopic.topic_id == topic.id))
    db.delete(topic)


def suggest_topics(db: Session, workspace_id: uuid.UUID, tz_name: str, limit: int = 15) -> dict:
    """Frequent distinctive terms in records that have no topic yet (TF-IDF). Statistical, not AI."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    stmt = apply_filters(select(FeedbackRecord.text), workspace_id, FeedbackFilter(), tz_name)
    stmt = stmt.where(~FeedbackRecord.id.in_(select(FeedbackTopic.feedback_id))).limit(5000)
    texts = [t for t in db.scalars(stmt) if t and len(t) > 10]
    if len(texts) < 10:
        return {"method": "tfidf", "documents": len(texts), "suggestions": [], "note": "At least 10 records without a topic are needed for suggestions."}
    word_pattern = r"(?u)\b[a-zA-Z][a-zA-Z]+\b"
    vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", min_df=max(3, len(texts) // 200), max_features=3000, token_pattern=word_pattern)
    try:
        matrix = vec.fit_transform(texts)
    except ValueError:
        return {"method": "tfidf", "documents": len(texts), "suggestions": [], "note": "Not enough recurring vocabulary for suggestions."}
    terms = vec.get_feature_names_out()
    scores = matrix.sum(axis=0).A1
    doc_freq = (matrix > 0).sum(axis=0).A1
    known = set()
    for t in db.scalars(select(Topic).where(Topic.workspace_id == workspace_id)):
        known.add(t.name.lower())
        known.update(k.lower().rstrip("*") for k in (t.keywords or []))
    ranked = sorted(range(len(terms)), key=lambda i: -scores[i])
    out = []
    for i in ranked:
        term = terms[i]
        if term in known or any(term.startswith(k) for k in known if len(k) > 3):
            continue
        out.append({"term": term, "documents": int(doc_freq[i]), "score": round(float(scores[i]), 3)})
        if len(out) >= limit:
            break
    return {
        "method": "tfidf",
        "documents": len(texts),
        "suggestions": out,
        "note": "Terms that frequently appear in records without a topic. Review before creating topics.",
    }
