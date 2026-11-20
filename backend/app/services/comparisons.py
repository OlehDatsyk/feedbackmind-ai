"""Comparison workspace: compare two segments (date ranges, products, sources or customer segments).

Segment A is the baseline, segment B the comparison. Differences in proportions are tested with a two-proportion
z-test; a topic is only called improving/declining when the test is significant and both sides meet the minimum
sample size. Warnings are returned whenever the comparison may be unreliable.
"""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.analytics import distribution, load_rows, topic_stats
from app.services.filters import FeedbackFilter
from app.services.stats import normal_approx_ok, pct, two_proportion_ztest

METHODOLOGY = (
    "Segment A is the baseline and segment B is compared against it. Sentiment percentages are shares of classified records. "
    "Topic negative shares use aspect-level sentiment where available. Differences are tested with a two-sided two-proportion "
    "z-test at alpha = 0.05; topics are labelled improving or declining only when the difference is significant and both segments "
    "have at least the minimum sample size. Observed differences do not establish causes."
)


class Segment(BaseModel):
    label: str = Field(default="", max_length=80)
    date_from: date | None = None
    date_to: date | None = None
    product_ids: list[uuid.UUID] = []
    source_ids: list[uuid.UUID] = []
    segment: str | None = None
    topic_ids: list[uuid.UUID] = []

    def to_filter(self) -> FeedbackFilter:
        return FeedbackFilter(
            date_from=self.date_from,
            date_to=self.date_to,
            product_ids=self.product_ids,
            source_ids=self.source_ids,
            segment=self.segment,
            topic_ids=self.topic_ids,
        )


def _overlap(a: Segment, b: Segment) -> bool:
    same_scope = set(a.product_ids) == set(b.product_ids) and set(a.source_ids) == set(b.source_ids) and a.segment == b.segment
    if not same_scope:
        return False
    if a.date_from is None or a.date_to is None or b.date_from is None or b.date_to is None:
        return True
    return not (a.date_to < b.date_from or b.date_to < a.date_from)


def compare(db: Session, workspace_id: uuid.UUID, tz_name: str, a: Segment, b: Segment) -> dict:
    min_n = get_settings().min_sample_size
    rows_a = load_rows(db, workspace_id, a.to_filter(), tz_name)
    rows_b = load_rows(db, workspace_id, b.to_filter(), tz_name)
    da, dbb = distribution(rows_a), distribution(rows_b)
    warnings: list[str] = []
    for name, d in (("A", da), ("B", dbb)):
        if d["total"] == 0:
            warnings.append(f"Segment {name} contains no feedback records.")
        elif d["classified"] < 30:
            warnings.append(f"Segment {name} has only {d['classified']} classified records; differences may not be reliable.")
    if _overlap(a, b):
        warnings.append("The two segments overlap (the same records may be counted in both), so they are not independent samples.")
    if a.date_from and a.date_to and b.date_from and b.date_to:
        la, lb = (a.date_to - a.date_from).days + 1, (b.date_to - b.date_from).days + 1
        if max(la, lb) > 1.5 * min(la, lb):
            warnings.append(f"Date ranges have different lengths ({la} vs {lb} days); compare shares rather than raw volumes.")
    ma, mb = da["methods"], dbb["methods"]
    ai_a = (ma["ai"] / da["classified"]) if da["classified"] else 0
    ai_b = (mb["ai"] / dbb["classified"]) if dbb["classified"] else 0
    if abs(ai_a - ai_b) > 0.25:
        warnings.append(
            "The segments were classified with different methods (AI vs rule-based) in different proportions; part of the difference may come from the method."
        )

    overall = None
    if da["classified"] and dbb["classified"]:
        t = two_proportion_ztest(da["counts"]["negative"], da["classified"], dbb["counts"]["negative"], dbb["classified"])
        if t:
            overall = {
                **t.__dict__,
                "valid": normal_approx_ok(da["counts"]["negative"], da["classified"]) and normal_approx_ok(dbb["counts"]["negative"], dbb["classified"]),
            }

    ta = {t["id"]: t for t in topic_stats(db, workspace_id, a.to_filter(), tz_name)}
    tb = {t["id"]: t for t in topic_stats(db, workspace_id, b.to_filter(), tz_name)}
    topics = []
    for tid in set(ta) | set(tb):
        x, y = ta.get(tid), tb.get(tid)
        name = (x or y)["name"]  # type: ignore[index]
        ca, cb = (x["count"] if x else 0), (y["count"] if y else 0)
        na, nb = (x["negative"] if x else 0), (y["negative"] if y else 0)
        cla = ca - (x["unclassified"] if x else 0)
        clb = cb - (y["unclassified"] if y else 0)
        test = two_proportion_ztest(na, cla, nb, clb) if cla >= min_n and clb >= min_n else None
        status = "insufficient_data"
        if test is not None:
            status = ("declining" if test.diff > 0 else "improving") if test.significant else "no_significant_change"
        if ca < 2 and cb >= min_n:
            status = "emerging"
        topics.append(
            {
                "id": tid,
                "name": name,
                "a_count": ca,
                "b_count": cb,
                "a_volume_share": pct(ca, da["total"]),
                "b_volume_share": pct(cb, dbb["total"]),
                "a_negative_share": pct(na, cla),
                "b_negative_share": pct(nb, clb),
                "p_value": round(test.p_value, 4) if test else None,
                "status": status,
            }
        )
    topics.sort(key=lambda t: -(t["a_count"] + t["b_count"]))
    return {
        "a": {"label": a.label or "Segment A", "summary": da},
        "b": {"label": b.label or "Segment B", "summary": dbb},
        "negative_share_test": overall,
        "topics": topics,
        "improving": [t for t in topics if t["status"] == "improving"],
        "declining": [t for t in topics if t["status"] == "declining"],
        "emerging": [t for t in topics if t["status"] == "emerging"],
        "warnings": warnings,
        "methodology": METHODOLOGY,
        "min_sample_size": min_n,
    }
