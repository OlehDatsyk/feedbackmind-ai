"""Feedback Hub CRUD, search, filters, duplicates, notes, tags, topics, archive and manual corrections."""

from __future__ import annotations

from tests.conftest import add_feedback, days_ago


def test_create_with_baseline_analysis(alice):
    fb = add_feedback(alice, "The delivery was terribly late and the courier was rude.", rating=1)
    assert fb["sentiment"]["label"] == "negative"
    assert fb["sentiment"]["method"] == "lexicon"
    assert fb["sentiment"]["confidence"] is None  # lexicon scores are not probabilities
    assert fb["source"]["name"] == "Manual entry"
    names = {t["name"] for t in fb["topics"]}
    assert "Delivery" in names
    assert fb["processing_status"] == "processed"
    assert fb["rating_max"] == 5.0


def test_anonymous_feedback_and_validation(alice):
    fb = add_feedback(alice, "Works fine")
    assert fb["customer_ref"] is None
    assert alice.post("/api/v1/feedback", json={"text": "   "}).status_code == 422
    assert alice.post("/api/v1/feedback", json={"text": "x", "rating": 7}).status_code == 422  # > default 5 scale
    assert alice.post("/api/v1/feedback", json={"text": "x", "received_at": "2999-01-01T00:00:00Z"}).status_code == 422
    assert alice.post("/api/v1/feedback", json={"text": "x" * 20001}).status_code == 422


def test_duplicate_detection(alice):
    when = days_ago(2)
    add_feedback(alice, "Great product, love it", received_at=when)
    r = alice.post("/api/v1/feedback", json={"text": "great   product, LOVE it", "received_at": when})
    assert r.status_code == 409
    r = alice.post("/api/v1/feedback", json={"text": "great product, love it", "received_at": when, "allow_duplicate": True})
    assert r.status_code == 201
    # Different customer reference is not a duplicate.
    r = alice.post("/api/v1/feedback", json={"text": "Great product, love it", "received_at": when, "customer_ref": "C-2"})
    assert r.status_code == 201


def test_update_preserves_history_and_reanalyses(alice):
    fb = add_feedback(alice, "I love this service")
    assert fb["sentiment"]["label"] == "positive"
    r = alice.patch(f"/api/v1/feedback/{fb['id']}", json={"text": "I hate this service, it is awful"})
    assert r.json()["sentiment"]["label"] == "negative"
    detail = alice.get(f"/api/v1/feedback/{fb['id']}").json()
    assert [a["label"] for a in detail["analyses"]] == ["negative", "positive"]
    activity = alice.get("/api/v1/workspace/activity").json()
    assert any(a["action"] == "feedback.updated" for a in activity)


def test_manual_correction_is_audited(alice):
    fb = add_feedback(alice, "Oh great, it broke again. Fantastic.")
    original = fb["sentiment"]["label"]
    r = alice.post(f"/api/v1/feedback/{fb['id']}/sentiment", json={"label": "negative", "note": "Sarcasm"})
    assert r.status_code == 200
    d = r.json()
    assert d["sentiment"]["label"] == "negative"
    assert d["sentiment"]["method"] == "manual"
    assert d["sentiment"]["score"] is None
    manual = d["analyses"][0]
    assert manual["method"] == "manual" and manual["previous_label"] == original and manual["corrected_by"] == "Test User"
    assert any(a["method"] == "lexicon" for a in d["analyses"])  # original result preserved
    assert alice.post(f"/api/v1/feedback/{fb['id']}/sentiment", json={"label": "furious"}).status_code == 422


def test_search_and_filters(alice):
    p = alice.post("/api/v1/products", json={"name": "Widget"}).json()
    s = alice.post("/api/v1/sources", json={"name": "Survey", "kind": "survey"}).json()
    add_feedback(alice, "Refund still not processed", product_id=p["id"], received_at=days_ago(1), tags=["billing"])
    add_feedback(alice, "Fantastic support team", source_id=s["id"], received_at=days_ago(40))
    add_feedback(alice, "100% off_topic text", received_at=days_ago(3))
    assert alice.get("/api/v1/feedback", params={"q": "refund"}).json()["total"] == 1
    assert alice.get("/api/v1/feedback", params={"q": "billing"}).json()["total"] == 1  # tag search
    assert alice.get("/api/v1/feedback", params={"q": "%"}).json()["total"] == 1  # LIKE wildcards are escaped
    assert alice.get("/api/v1/feedback", params={"q": "_"}).json()["total"] == 1
    assert alice.get("/api/v1/feedback", params={"product_id": p["id"]}).json()["total"] == 1
    assert alice.get("/api/v1/feedback", params={"source_id": s["id"]}).json()["total"] == 1
    assert alice.get("/api/v1/feedback", params={"sentiment": "positive"}).json()["total"] >= 1
    from datetime import UTC, datetime, timedelta

    since = (datetime.now(UTC) - timedelta(days=10)).date().isoformat()
    assert alice.get("/api/v1/feedback", params={"date_from": since}).json()["total"] == 2
    topics = alice.get("/api/v1/topics").json()
    refunds = next(t for t in topics if t["name"] == "Refunds")
    assert alice.get("/api/v1/feedback", params={"topic_id": refunds["id"]}).json()["total"] == 1
    page = alice.get("/api/v1/feedback", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 1


def test_notes_tags_topics_review_archive(alice):
    fb = add_feedback(alice, "The checkout page keeps failing")
    n = alice.post(f"/api/v1/feedback/{fb['id']}/notes", json={"body": "Escalated to web team"}).json()
    r = alice.put(f"/api/v1/feedback/{fb['id']}/tags", json={"tags": ["web", "urgent", "web"]})
    assert sorted(t["name"] for t in r.json()["tags"]) == ["urgent", "web"]
    topic = alice.post("/api/v1/topics", json={"name": "Checkout", "keywords": ["checkout"]}).json()
    r = alice.post(f"/api/v1/feedback/{fb['id']}/topics", json={"topic_id": topic["id"], "sentiment": "negative"})
    assert any(t["name"] == "Checkout" and t["assigned_by"] == "manual" for t in r.json()["topics"])
    r = alice.patch(f"/api/v1/feedback/{fb['id']}", json={"needs_review": True})
    assert r.json()["needs_review"] is True
    assert alice.get("/api/v1/feedback", params={"needs_review": True}).json()["total"] == 1
    alice.post("/api/v1/feedback/bulk", json={"ids": [fb["id"]], "action": "archive"})
    assert alice.get("/api/v1/feedback").json()["total"] == 0
    assert alice.get("/api/v1/feedback", params={"archived_only": True}).json()["total"] == 1
    assert alice.get("/api/v1/analytics/overview").json()["distribution"]["total"] == 0  # archived excluded
    detail = alice.get(f"/api/v1/feedback/{fb['id']}").json()
    assert detail["notes"][0]["body"] == "Escalated to web team"
    assert alice.delete(f"/api/v1/feedback/{fb['id']}/notes/{n['id']}").status_code == 204


def test_delete_is_permanent(alice):
    fb = add_feedback(alice, "To be deleted")
    assert alice.delete(f"/api/v1/feedback/{fb['id']}").status_code == 204
    assert alice.get(f"/api/v1/feedback/{fb['id']}").status_code == 404


def test_xss_payload_stored_as_text(alice):
    payload = "<script>alert('x')</script> great"
    fb = add_feedback(alice, payload)
    assert alice.get(f"/api/v1/feedback/{fb['id']}").json()["text"] == payload  # stored verbatim, rendered as text by the UI
