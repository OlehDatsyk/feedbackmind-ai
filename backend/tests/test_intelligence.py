"""Insights, alerts, comparisons, reports, integrations and demo data."""

from __future__ import annotations

import csv
import io
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

from app.db.session import SessionLocal
from app.models import Topic
from app.services.integrations import sign
from tests.conftest import add_feedback, add_member, days_ago, run_jobs
from tests.test_analytics import seed


def _topic_id(ws_id: str, name: str):
    with SessionLocal() as db:
        return db.query(Topic).filter(Topic.workspace_id == uuid.UUID(ws_id), Topic.name == name).one().id


def _now():
    return datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)


def test_insights_supported_by_records(alice, fake_ai):
    tid = _topic_id(alice.workspace_id, "Delivery")
    now = _now()
    seed(
        alice.workspace_id,
        [{"at": now - timedelta(days=i % 20), "label": "negative", "score": -0.6, "topics": [(tid, None)], "text": f"late delivery {i}"} for i in range(12)],
    )
    seed(alice.workspace_id, [{"at": now - timedelta(days=i % 20), "label": "positive", "score": 0.6} for i in range(10)])
    r = alice.post("/api/v1/insights/generate", json={"with_ai_narrative": True})
    assert r.status_code == 200
    ins = r.json()["insights"]
    rec = next(i for i in ins if i["kind"] == "recurring_issue")
    assert rec["topic"]["name"] == "Delivery" and rec["supporting_count"] == 12 and rec["evidence_strength"] == "moderate"
    assert rec["generated_by"] == "rules" and rec["suggested_action"]
    detail = alice.get(f"/api/v1/insights/{rec['id']}").json()
    assert 1 <= len(detail["evidence"]) <= 5 and all("late delivery" in e["text"] for e in detail["evidence"])
    run_jobs()
    detail = alice.get(f"/api/v1/insights/{rec['id']}").json()
    assert detail["ai_summary"] == "AI summary." and detail["ai_model"] == "claude-opus-5-5"
    assert detail["description"].startswith("12 of 12")  # facts unchanged by AI


def test_small_samples_do_not_create_insights(alice):
    tid = _topic_id(alice.workspace_id, "Pricing")
    seed(alice.workspace_id, [{"at": _now(), "label": "negative", "score": -0.6, "topics": [(tid, None)]} for _ in range(3)])
    assert alice.post("/api/v1/insights/generate", json={}).json()["insights"] == []


def test_insight_ai_narrative_requires_ai(alice):
    assert alice.post("/api/v1/insights/generate", json={"with_ai_narrative": True}).status_code == 400


def test_alert_rules_trigger_only_when_conditions_met(alice):
    now = _now()
    r = alice.post("/api/v1/alerts/rules", json={"name": "Neg spike", "alert_type": "negative_spike", "threshold": 50, "window_days": 7, "min_count": 5}).json()
    assert alice.post("/api/v1/alerts/evaluate").json()["triggered"] == []  # no data -> no alert
    seed(alice.workspace_id, [{"at": now - timedelta(days=10), "label": "negative", "score": -0.5}] * 4)  # previous window: 4
    seed(alice.workspace_id, [{"at": now - timedelta(days=2), "label": "negative", "score": -0.5}] * 5)  # current: 5 (+25%)
    assert alice.post("/api/v1/alerts/evaluate").json()["triggered"] == []  # below threshold
    seed(alice.workspace_id, [{"at": now - timedelta(days=1), "label": "negative", "score": -0.5}] * 2)  # current: 7 (+75%)
    ev = alice.post("/api/v1/alerts/evaluate").json()["triggered"]
    assert len(ev) == 1 and ev[0]["metrics"]["current_negative"] == 7 and ev[0]["metrics"]["previous_negative"] == 4
    assert "75.0%" in ev[0]["explanation"] and len(ev[0]["evidence_ids"]) == 7
    assert alice.post("/api/v1/alerts/evaluate").json()["triggered"] == []  # cooldown prevents repeats
    events = alice.get("/api/v1/alerts/events").json()
    assert events["unread"] == 1
    alice.patch(f"/api/v1/alerts/events/{ev[0]['id']}", json={"status": "resolved", "is_read": True})
    assert alice.get("/api/v1/alerts/events").json()["unread"] == 0
    alice.patch(f"/api/v1/alerts/rules/{r['id']}", json={"is_enabled": False})


def test_alert_types(alice):
    now = _now()
    alice.post("/api/v1/alerts/rules", json={"name": "share", "alert_type": "negative_share", "threshold": 40, "window_days": 7, "min_count": 5})
    alice.post("/api/v1/alerts/rules", json={"name": "vol", "alert_type": "volume_spike", "threshold": 100, "window_days": 7, "min_count": 5})
    alice.post("/api/v1/alerts/rules", json={"name": "new", "alert_type": "new_topic", "threshold": 0, "window_days": 7, "min_count": 3})
    tid = _topic_id(alice.workspace_id, "Refunds")
    seed(alice.workspace_id, [{"at": now - timedelta(days=9), "label": "positive", "score": 0.5}] * 2)
    seed(
        alice.workspace_id,
        [{"at": now - timedelta(days=1), "label": "negative", "score": -0.5, "topics": [(tid, None)]}] * 3
        + [{"at": now, "label": "positive", "score": 0.5}] * 2,
    )
    types = {e["alert_type"] for e in alice.post("/api/v1/alerts/evaluate").json()["triggered"]}
    assert types == {"negative_share", "volume_spike", "new_topic"}
    assert alice.post("/api/v1/alerts/rules", json={"name": "x", "alert_type": "product_complaints", "threshold": 10}).status_code == 422
    assert alice.post("/api/v1/alerts/rules", json={"name": "x", "alert_type": "bogus", "threshold": 10}).status_code == 422


def test_comparison_methodology_and_warnings(alice):
    with SessionLocal() as db:
        from app.models import Product

        a, b = Product(workspace_id=uuid.UUID(alice.workspace_id), name="A"), Product(workspace_id=uuid.UUID(alice.workspace_id), name="B")
        db.add_all([a, b])
        db.commit()
        pa, pb = a.id, b.id
    now = _now()
    seed(alice.workspace_id, [{"at": now, "label": "negative" if i < 5 else "positive", "score": 0, "product_id": pa} for i in range(50)])
    seed(alice.workspace_id, [{"at": now, "label": "negative" if i < 30 else "positive", "score": 0, "product_id": pb} for i in range(50)])
    r = alice.post("/api/v1/comparisons", json={"a": {"label": "A", "product_ids": [str(pa)]}, "b": {"label": "B", "product_ids": [str(pb)]}}).json()
    assert r["a"]["summary"]["percentages"]["negative"] == 10.0 and r["b"]["summary"]["percentages"]["negative"] == 60.0
    assert r["negative_share_test"]["significant"] is True
    assert "z-test" in r["methodology"] and r["warnings"] == []
    small = alice.post(
        "/api/v1/comparisons", json={"a": {"date_from": "2020-01-01", "date_to": "2020-01-31"}, "b": {"date_from": "2020-01-15", "date_to": "2020-03-31"}}
    ).json()
    joined = " ".join(small["warnings"])
    assert "no feedback records" in joined and "overlap" in joined and "different lengths" in joined


def _download(acct, rid):
    r = acct.get(f"/api/v1/reports/{rid}/download")
    assert r.status_code == 200, r.text
    return r


def test_reports_all_formats(alice):
    add_feedback(alice, "=cmd|' /C calc'!A0 terrible delivery", received_at=days_ago(1))
    add_feedback(alice, "Great quality, love it", received_at=days_ago(2))
    ids = {}
    for fmt in ("pdf", "docx", "xlsx", "csv"):
        r = alice.post("/api/v1/reports", json={"format": fmt, "title": f"Test {fmt}"})
        assert r.status_code == 202
        ids[fmt] = r.json()["id"]
    run_jobs()
    for rid in ids.values():
        rep = alice.get(f"/api/v1/reports/{rid}").json()
        assert rep["status"] == "ready" and rep["record_count"] == 2, rep
    assert _download(alice, ids["pdf"]).content.startswith(b"%PDF")
    assert _download(alice, ids["docx"]).content.startswith(b"PK")
    body = _download(alice, ids["csv"]).content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0][0] == "id" and len(rows) == 3
    assert any(r[2].startswith("'=cmd") for r in rows[1:])  # formula neutralised
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(_download(alice, ids["xlsx"]).content))
    assert {"Summary", "Topics", "Insights", "Records", "Methodology"} <= set(wb.sheetnames)
    texts = [c.value for c in wb["Records"]["C"]][1:]
    assert all(not str(t).startswith("=") for t in texts)


def test_report_filters_and_permissions(alice, bob):
    add_feedback(alice, "Old one", received_at="2025-01-01T10:00:00Z")
    add_feedback(alice, "New one", received_at=days_ago(1))
    rid = alice.post("/api/v1/reports", json={"format": "csv", "filters": {"date_from": "2025-01-01", "date_to": "2025-01-31"}}).json()["id"]
    run_jobs()
    body = _download(alice, rid).content.decode("utf-8-sig")
    assert "Old one" in body and "New one" not in body
    assert bob.get(f"/api/v1/reports/{rid}/download").status_code == 404
    viewer = add_member(alice, "v@example.com", "viewer")
    assert viewer.get(f"/api/v1/reports/{rid}/download").status_code == 200


def test_rest_api_ingestion(client, alice):
    r = alice.post("/api/v1/integrations", json={"provider": "rest_api", "name": "Website widget"})
    assert r.status_code == 201
    key = r.json()["api_key"]
    listing = alice.get("/api/v1/integrations").json()
    assert key not in json.dumps(listing) and listing["configured"][0]["key_prefix"] == key[:12]
    statuses = {c["provider"]: c["status"] for c in listing["catalog"]}
    assert statuses["zendesk"] == "not_implemented" and statuses["rest_api"] == "available"
    body = {"records": [{"text": "Love the new widget", "external_id": "w-1"}, {"text": "x", "received_at": "2999-01-01T00:00:00Z"}]}
    assert client.post("/api/v1/ingest/feedback", json=body).status_code == 401
    assert client.post("/api/v1/ingest/feedback", json=body, headers={"X-API-Key": "fm_live_wrong"}).status_code == 401
    res = client.post("/api/v1/ingest/feedback", json=body, headers={"X-API-Key": key}).json()
    assert len(res["created"]) == 1 and len(res["errors"]) == 1
    again = client.post("/api/v1/ingest/feedback", json={"records": [{"text": "Love the new widget", "external_id": "w-1"}]}, headers={"X-API-Key": key}).json()
    assert again["duplicates"][0]["reason"].startswith("external_id")
    item = alice.get("/api/v1/feedback").json()["items"][0]
    assert item["source"]["name"] == "API: Website widget"


def test_signed_webhook(client, alice):
    r = alice.post("/api/v1/integrations", json={"provider": "webhook", "name": "Helpdesk"}).json()
    secret, wid = r["signing_secret"], r["id"]
    payload = json.dumps({"text": "Agent solved it quickly", "product": "Support Plan"}).encode()
    ts = str(int(time.time()))
    url = f"/api/v1/ingest/webhooks/{wid}"
    good = {"X-FeedbackMind-Timestamp": ts, "X-FeedbackMind-Signature": sign(secret, ts, payload), "Content-Type": "application/json"}
    assert client.post(url, content=payload, headers={**good, "X-FeedbackMind-Signature": "sha256=deadbeef"}).status_code == 401
    old_ts = str(int(time.time()) - 3600)
    assert (
        client.post(
            url, content=payload, headers={**good, "X-FeedbackMind-Timestamp": old_ts, "X-FeedbackMind-Signature": sign(secret, old_ts, payload)}
        ).status_code
        == 401
    )
    assert client.post(f"/api/v1/ingest/webhooks/{uuid.uuid4()}", content=payload, headers=good).status_code == 401
    res = client.post(url, content=payload, headers=good)
    assert res.status_code == 200 and len(res.json()["created"]) == 1
    assert alice.get("/api/v1/feedback").json()["items"][0]["product"]["name"] == "Support Plan"
    alice.patch(f"/api/v1/integrations/{wid}", json={"status": "disabled"})
    assert client.post(url, content=payload, headers=good).status_code == 401


def test_demo_data_is_labelled_and_removable(alice):
    real = add_feedback(alice, "A real customer comment")
    r = alice.post("/api/v1/workspace/demo")
    assert r.status_code == 200 and r.json()["demo_records"] == 240
    assert alice.post("/api/v1/workspace/demo").status_code == 409
    o = alice.get("/api/v1/analytics/overview").json()
    assert o["demo_records"] == 240 and o["distribution"]["total"] == 241
    demo = alice.get("/api/v1/feedback", params={"is_demo": True, "limit": 1}).json()["items"][0]
    assert demo["is_demo"] is True and "demo" in demo["source"]["name"].lower()
    assert alice.delete("/api/v1/workspace/demo").json()["removed"] == 240
    left = alice.get("/api/v1/feedback").json()
    assert left["total"] == 1 and left["items"][0]["id"] == real["id"]


def test_topic_management(alice):
    t1 = alice.post("/api/v1/topics", json={"name": "Shipping speed", "keywords": ["shipping", "Fast*"]}).json()
    assert t1["keywords"] == ["shipping", "fast*"]
    assert alice.post("/api/v1/topics", json={"name": "Shipping speed"}).status_code == 409
    fb = add_feedback(alice, "Shipping was fast")
    assert any(t["name"] == "Shipping speed" for t in fb["topics"])
    delivery = next(t for t in alice.get("/api/v1/topics").json() if t["name"] == "Delivery")
    r = alice.post("/api/v1/topics/merge", json={"source_id": t1["id"], "target_id": delivery["id"]}).json()
    assert "fast*" in r["target"]["keywords"]
    d = alice.get(f"/api/v1/feedback/{fb['id']}").json()
    names = [t["name"] for t in d["topics"]]
    assert "Delivery" in names and "Shipping speed" not in names
    assert alice.patch(f"/api/v1/topics/{delivery['id']}", json={"name": "Delivery & shipping"}).json()["name"] == "Delivery & shipping"
    job = alice.post("/api/v1/topics/reapply-rules").json()
    run_jobs()
    assert alice.get(f"/api/v1/jobs/{job['id']}").json()["status"] == "succeeded"
    for i in range(12):
        add_feedback(alice, f"The gizmo widget thingamajig needs work number {i}", received_at=days_ago(i + 1))
    sug = alice.get("/api/v1/topics/suggestions").json()
    assert sug["method"] == "tfidf" and any("gizmo" in s["term"] for s in sug["suggestions"])
