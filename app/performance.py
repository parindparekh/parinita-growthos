"""Outcome telemetry and transparent performance learning for GrowthOS."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import PerformanceEvent


def _d(v: str) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def summarize(db: Session, *, content_id: str | None = None, days: int = 30) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))
    q = db.query(PerformanceEvent).filter(PerformanceEvent.created_at >= cutoff)
    if content_id:
        q = q.filter(PerformanceEvent.content_id == content_id)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    channels: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    rows = q.all()
    for e in rows:
        v = _d(e.value)
        totals[e.metric] += v
        channels[e.channel or "unknown"][e.metric] += v

    def ratio(a: Decimal, b: Decimal) -> float:
        return round(float(a / b), 6) if b else 0.0

    derived = {
        "click_through_rate": ratio(totals["clicks"], totals["impressions"] or totals["views"]),
        "engagement_rate": ratio(totals["engagements"], totals["impressions"] or totals["views"]),
        "conversion_rate": ratio(totals["conversions"], totals["clicks"]),
    }
    by_channel = {}
    for ch, m in channels.items():
        base = m["impressions"] or m["views"]
        by_channel[ch] = {"metrics": {k: float(v) for k, v in sorted(m.items())},
                          "ctr": ratio(m["clicks"], base),
                          "engagement_rate": ratio(m["engagements"], base),
                          "conversion_rate": ratio(m["conversions"], m["clicks"])}
    return {"content_id": content_id, "days": days, "events": len(rows),
            "totals": {k: float(v) for k, v in sorted(totals.items())}, "derived": derived,
            "by_channel": by_channel}


def learn(db: Session, *, content_id: str | None = None, days: int = 30) -> dict:
    s = summarize(db, content_id=content_id, days=days)
    actions = []
    totals = s["totals"]
    impressions = totals.get("impressions", 0) or totals.get("views", 0)
    if not s["events"]:
        actions.append({"priority": "high", "action": "connect-performance-feed", "why": "No outcome events are recorded."})
    else:
        if impressions >= 1000 and s["derived"]["click_through_rate"] < 0.005:
            actions.append({"priority": "normal", "action": "test-cta-or-opening-copy", "why": "Observed click-through is below 0.5% on at least 1,000 impressions/views."})
        if totals.get("clicks", 0) >= 100 and s["derived"]["conversion_rate"] < 0.01:
            actions.append({"priority": "normal", "action": "inspect-landing-path", "why": "Observed conversion is below 1% after at least 100 clicks."})
        if s["by_channel"]:
            best = max(s["by_channel"].items(), key=lambda kv: (kv[1]["conversion_rate"], kv[1]["ctr"], kv[1]["engagement_rate"]))
            actions.append({"priority": "normal", "action": "review-channel-mix", "why": f"{best[0]} currently has the strongest observed conversion/CTR/engagement tuple."})
    return {"summary": s, "actions": actions,
            "note": "Learning is based only on recorded telemetry. It does not infer causation from correlation."}
