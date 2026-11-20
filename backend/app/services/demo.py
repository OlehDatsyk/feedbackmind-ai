"""Optional sample dataset for evaluation.

Every generated record is flagged ``is_demo=True``, attached to a source called "Demo data (synthetic)", and shown
with a DEMO badge in the UI. The sentences are synthetic templates written for this application - they are not real
customer feedback. Demo data can be removed at any time without touching real records.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import FeedbackRecord, FeedbackSource
from app.services.analysis import active_topics, ensure_default_topics
from app.services.feedback import NewFeedback, create_record, get_or_create_product, get_or_create_source

DEMO_SOURCE = "Demo data (synthetic)"

TEMPLATES = {
    "negative": [
        "Delivery took almost two weeks and nobody kept me posted about the delay.",
        "The package arrived damaged and the box was crushed.",
        "Customer support was rude and did not resolve my issue.",
        "The app keeps crashing every time I open the checkout page.",
        "Way too expensive for what you get, the price went up again.",
        "I asked for a refund three weeks ago and still have not received it.",
        "The website is confusing and I could not find my order history.",
        "Very slow loading times, the dashboard freezes constantly.",
        "Quality has dropped, the handle broke after one week.",
        "The documentation is outdated and the instructions are unclear.",
        "Shipping was late again, this is the third time this month.",
        "Billing charged me twice and the support agent could not explain why.",
    ],
    "positive": [
        "Fast delivery and the packaging was excellent.",
        "The support team was incredibly helpful and solved my problem in minutes.",
        "Great quality, it feels sturdy and well made.",
        "Love the new reporting feature, it saves me hours every week.",
        "The interface is intuitive and easy to use.",
        "Good value for money compared with other options.",
        "Thank you for the quick refund, very smooth process.",
        "The app is fast and reliable, no issues at all.",
    ],
    "neutral": [
        "I ordered the product on Monday and it arrived on Thursday.",
        "Is there an option to export data to a spreadsheet?",
        "I changed my subscription plan last week.",
        "The manual covers the basic setup steps.",
    ],
    "mixed": [
        "The product quality is great but delivery took far too long.",
        "Support was friendly, however the refund process is slow and confusing.",
        "I like the features but the price is too high for small teams.",
    ],
}
PRODUCTS = ["Aurora Desk Lamp", "Nimbus Mobile App", "Atlas Subscription"]
SOURCES = ["App store reviews", "Support tickets", "NPS survey"]
SEGMENTS = ["Consumer", "Small business", "Enterprise"]


def load_demo_data(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID | None, n: int = 240, days: int = 120, seed: int = 42) -> int:
    ensure_default_topics(db, workspace_id)
    rng = random.Random(seed)  # deterministic dataset
    topics = active_topics(db, workspace_id)
    demo_source = get_or_create_source(db, workspace_id, DEMO_SOURCE, "demo")
    products = [get_or_create_product(db, workspace_id, p) for p in PRODUCTS]
    sub_sources = [get_or_create_source(db, workspace_id, f"{s} (demo)", "demo") for s in SOURCES]
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    created = 0
    for i in range(n):
        age = rng.random() ** 0.8 * days  # slightly more recent feedback
        when = now - timedelta(days=age, hours=rng.randint(0, 23))
        recent = age < 30
        # Built-in story: delivery complaints rise in the most recent month.
        weights = {"negative": 0.45 if recent else 0.3, "positive": 0.4 if not recent else 0.3, "neutral": 0.15, "mixed": 0.1}
        label = rng.choices(list(weights), weights=list(weights.values()))[0]
        text = rng.choice(TEMPLATES[label])
        if recent and label == "negative" and rng.random() < 0.4:
            text = rng.choice([t for t in TEMPLATES["negative"] if "eliver" in t or "hipping" in t or "package" in t])
        rating = {"negative": rng.choice([1, 2]), "positive": rng.choice([4, 5]), "neutral": 3, "mixed": rng.choice([2, 3, 4])}[label]
        create_record(
            db,
            workspace_id,
            NewFeedback(
                text=text,
                received_at=when,
                source=rng.choice(sub_sources) if rng.random() < 0.8 else demo_source,
                product=rng.choice(products),
                customer_ref=f"DEMO-{i + 1:04d}",
                customer_segment=rng.choice(SEGMENTS),
                rating=float(rating),
                rating_max=5.0,
                is_demo=True,
            ),
            user_id,
            topics,
            flush=False,
        )
        created += 1
        if created % 100 == 0:
            db.flush()
    db.flush()
    return created


def demo_count(db: Session, workspace_id: uuid.UUID) -> int:
    return int(db.scalar(select(func.count(FeedbackRecord.id)).where(FeedbackRecord.workspace_id == workspace_id, FeedbackRecord.is_demo.is_(True))) or 0)


def remove_demo_data(db: Session, workspace_id: uuid.UUID) -> int:
    n = demo_count(db, workspace_id)
    db.execute(delete(FeedbackRecord).where(FeedbackRecord.workspace_id == workspace_id, FeedbackRecord.is_demo.is_(True)))
    # Remove demo-only sources that no longer have records.
    for src in db.scalars(select(FeedbackSource).where(FeedbackSource.workspace_id == workspace_id, FeedbackSource.kind == "demo")):
        if not db.scalar(select(func.count(FeedbackRecord.id)).where(FeedbackRecord.source_id == src.id)):
            db.delete(src)
    return n
