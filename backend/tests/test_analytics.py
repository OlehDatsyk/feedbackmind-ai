"""Analytics accuracy with controlled datasets whose expected results are known in advance."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.db.session import SessionLocal
from app.models import FeedbackRecord, FeedbackTopic, Product, Topic
from app.services.stats import linear_trend, pct, two_proportion_ztest
from app.services.textutil import content_hash


def seed(ws_id: str, items: list[dict]) -> list[str]:
    """Insert records with exact labels/scores (bypasses the analyser) so expected values are known."""
    ids = []
    with SessionLocal() as db:
        wid = uuid.UUID(ws_id)
        for it in items:
            rid = uuid.uuid4()
            rec = FeedbackRecord(
                id=rid,
                workspace_id=wid,
                text=it.get("text", f"record {rid}"),
                received_at=it["at"],
                sentiment_label=it.get("label"),
                sentiment_score=it.get("score"),
                sentiment_method=it.get("method", "ai" if it.get("label") else None),
                product_id=it.get("product_id"),
                is_archived=it.get("archived", False),
                content_hash=content_hash(str(rid), None, None),
                processing_status="processed",
            )
            db.add(rec)
            db.flush()
            for tid, sent in it.get("topics", []):
                db.add(FeedbackTopic(feedback_id=rid, topic_id=tid, sentiment=sent, assigned_by="manual"))
            ids.append(str(rid))
        db.commit()
    return ids


def at(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=UTC)


def test_stats_helpers():
    assert pct(1, 3) == 33.3
    assert pct(0, 0) is None  # never a misleading 0%
    t = two_proportion_ztest(10, 100, 30, 100)
    # Reference: pooled p=0.2, se=sqrt(.2*.8*(2/100))=0.05657, z=3.5355, p=0.000407
    assert math.isclose(t.z, 3.5355, rel_tol=1e-3)
    assert math.isclose(t.p_value, 0.000407, rel_tol=1e-2)
    assert t.significant
    assert two_proportion_ztest(1, 0, 1, 10) is None
    assert not two_proportion_ztest(5, 10, 6, 10).significant
    lt = linear_trend([10, 20, 30, 40, 50])
    assert lt.significant and math.isclose(lt.slope, 10.0)
    assert linear_trend([1, 2, 3]) is None  # too few points
    assert not linear_trend([5, 5, 5, 5]).significant


def test_distribution_denominators(alice):
    items = (
        [{"at": at(2026, 1, 10), "label": "positive", "score": 0.5}] * 3
        + [{"at": at(2026, 1, 10), "label": "negative", "score": -0.5}] * 2
        + [{"at": at(2026, 1, 10), "label": "neutral", "score": 0.0}] * 1
        + [{"at": at(2026, 1, 10), "label": "mixed", "score": None, "method": "manual"}] * 1
        + [{"at": at(2026, 1, 10), "label": None}] * 3  # unclassified
        + [{"at": at(2026, 1, 10), "label": "negative", "score": -1.0, "archived": True}]  # excluded
    )
    seed(alice.workspace_id, items)
    d = alice.get("/api/v1/analytics/overview").json()["distribution"]
    assert d["total"] == 10 and d["classified"] == 7 and d["unclassified"] == 3
    assert d["counts"] == {"positive": 3, "negative": 2, "neutral": 1, "mixed": 1, "uncertain": 0}
    assert d["percentages"]["positive"] == 42.9  # 3/7, not 3/10
    assert d["percentages"]["negative"] == 28.6
    assert d["percentages"]["uncertain"] == 0.0
    # mean of (0.5*3, -0.5*2, 0) over 6 scored records = 0.5/6
    assert d["average_score"] == round(0.5 / 6, 3) and d["average_score_n"] == 6
    assert d["methods"] == {"lexicon": 0, "ai": 6, "manual": 1}


def test_empty_dataset(alice):
    o = alice.get("/api/v1/analytics/overview").json()
    assert o["distribution"]["total"] == 0
    assert o["distribution"]["percentages"]["positive"] is None
    assert o["distribution"]["average_score"] is None
    assert o["timeseries"]["buckets"] == []
    assert o["trend"]["status"] == "insufficient_data"


def test_date_filter_inclusive_and_timezone_boundaries(alice):
    alice.patch("/api/v1/workspace", json={"timezone": "Asia/Tokyo"})  # UTC+9
    seed(
        alice.workspace_id,
        [
            {"at": datetime(2026, 2, 28, 14, 59, tzinfo=UTC), "label": "positive", "score": 1},  # 23:59 JST Feb 28
            {"at": datetime(2026, 2, 28, 15, 0, tzinfo=UTC), "label": "negative", "score": -1},  # 00:00 JST Mar 1
            {"at": datetime(2026, 3, 31, 14, 59, tzinfo=UTC), "label": "negative", "score": -1},  # 23:59 JST Mar 31
            {"at": datetime(2026, 3, 31, 15, 0, tzinfo=UTC), "label": "positive", "score": 1},  # Apr 1 JST
        ],
    )
    march = alice.get("/api/v1/analytics/overview", params={"date_from": "2026-03-01", "date_to": "2026-03-31"}).json()
    assert march["distribution"]["total"] == 2 and march["distribution"]["counts"]["negative"] == 2
    # Charts and cards use the same filtered records.
    assert sum(b["total"] for b in march["timeseries"]["buckets"]) == 2
    assert alice.get("/api/v1/feedback", params={"date_from": "2026-03-01", "date_to": "2026-03-31"}).json()["total"] == 2
    monthly = alice.get("/api/v1/analytics/timeseries", params={"granularity": "month", "date_from": "2026-02-01", "date_to": "2026-04-30"}).json()
    assert [(b["bucket"], b["total"]) for b in monthly["buckets"]] == [("2026-02-01", 1), ("2026-03-01", 2), ("2026-04-01", 1)]


def test_weekly_buckets_and_low_sample_flags(alice):
    items = [{"at": at(2026, 1, 5) + timedelta(days=i % 7), "label": "positive", "score": 0.5} for i in range(6)]  # week of Jan 5 (Mon)
    items += [{"at": at(2026, 1, 12), "label": "negative", "score": -0.5}]
    seed(alice.workspace_id, items)
    s = alice.get("/api/v1/analytics/timeseries", params={"granularity": "week", "date_from": "2026-01-05", "date_to": "2026-01-25"}).json()
    b = {x["bucket"]: x for x in s["buckets"]}
    assert list(b) == ["2026-01-05", "2026-01-12", "2026-01-19"]  # empty weeks are kept, not hidden
    assert b["2026-01-05"]["total"] == 6 and not b["2026-01-05"]["low_sample"]
    assert b["2026-01-12"]["total"] == 1 and b["2026-01-12"]["low_sample"]
    assert b["2026-01-19"]["total"] == 0 and b["2026-01-19"]["negative_share"] is None


def test_topic_stats_use_aspect_sentiment(alice):
    with SessionLocal() as db:
        t = db.query(Topic).filter(Topic.workspace_id == uuid.UUID(alice.workspace_id), Topic.name == "Delivery").one()
        tid = t.id
    seed(
        alice.workspace_id,
        [
            {"at": at(2026, 1, 1), "label": "positive", "score": 0.4, "topics": [(tid, "negative")]},  # mixed review: delivery negative
            {"at": at(2026, 1, 2), "label": "negative", "score": -0.4, "topics": [(tid, None)]},  # falls back to record label
            {"at": at(2026, 1, 3), "label": "positive", "score": 0.4, "topics": [(tid, "positive")]},
        ],
    )
    topics = alice.get("/api/v1/topics").json()
    d = next(x for x in topics if x["name"] == "Delivery")["stats"]
    assert d["count"] == 3 and d["negative"] == 2 and d["positive"] == 1
    assert d["negative_share"] == 66.7 and d["low_sample"] is True


def test_breakdown_by_product(alice):
    with SessionLocal() as db:
        p = Product(workspace_id=uuid.UUID(alice.workspace_id), name="Lamp")
        db.add(p)
        db.commit()
        pid = p.id
    seed(
        alice.workspace_id,
        [{"at": at(2026, 1, 1), "label": "negative", "score": -1, "product_id": pid}] * 3 + [{"at": at(2026, 1, 1), "label": "positive", "score": 1}] * 2,
    )
    rows = alice.get("/api/v1/analytics/breakdown", params={"dimension": "product"}).json()
    lamp = next(r for r in rows if r["name"] == "Lamp")
    none = next(r for r in rows if r["id"] is None)
    assert lamp["count"] == 3 and lamp["negative_share"] == 100.0
    assert none["count"] == 2 and none["negative_share"] == 0.0


def test_trend_detection_significance(alice):
    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        tid = db.query(Topic).filter(Topic.workspace_id == uuid.UUID(alice.workspace_id), Topic.name == "Pricing").one().id
    prev = [
        {"at": today - timedelta(days=45 + i % 10), "label": "negative" if i < 5 else "positive", "score": -0.5 if i < 5 else 0.5, "topics": [(tid, None)]}
        for i in range(40)
    ]
    cur = [
        {"at": today - timedelta(days=i % 20), "label": "negative" if i < 25 else "positive", "score": -0.5 if i < 25 else 0.5, "topics": [(tid, None)]}
        for i in range(40)
    ]
    seed(alice.workspace_id, prev + cur)
    d_to = today.date()
    d_from = d_to - timedelta(days=29)
    t = alice.get("/api/v1/trends", params={"date_from": d_from.isoformat(), "date_to": d_to.isoformat()}).json()
    pricing = next(x for x in t["period_comparison"]["topics"] if x["name"] == "Pricing")
    assert pricing["current_count"] == 40 and pricing["previous_count"] == 40
    assert pricing["previous_negative_share"] == 12.5 and pricing["current_negative_share"] == 62.5
    assert pricing["negative_share_test"]["significant"] is True
    assert "cause" in " ".join(t["notes"]).lower()


@pytest.mark.parametrize("granularity", ["day", "week", "month"])
def test_granularities_cover_all_records(alice, granularity):
    seed(alice.workspace_id, [{"at": at(2026, 1, 1) + timedelta(days=i * 3), "label": "neutral", "score": 0} for i in range(30)])
    s = alice.get("/api/v1/analytics/timeseries", params={"granularity": granularity}).json()
    assert sum(b["total"] for b in s["buckets"]) == 30


def test_auto_granularity_bounds(alice):
    seed(alice.workspace_id, [{"at": at(2020, 1, 1), "label": "neutral", "score": 0}, {"at": at(2026, 1, 1), "label": "neutral", "score": 0}])
    s = alice.get("/api/v1/analytics/timeseries", params={"granularity": "day"}).json()
    assert s["granularity"] == "week" and len(s["buckets"]) <= 400  # 6 years of days (>400) is coarsened
    assert date.fromisoformat(s["buckets"][0]["bucket"]) == date(2019, 12, 30)  # Monday of that week
