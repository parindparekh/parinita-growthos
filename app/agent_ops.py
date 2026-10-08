"""System-level agent operations that do real work beyond repackaging one release."""
from __future__ import annotations
from .agent_names import display_name

import json
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .audit import record_event
from .content import governed_hash
from .feed_fabric import GateBlocked, PolicyBlocked, push_content
from .gate import evaluate
from .models import ContentItem, FeedEndpoint, InboxMessage, ScheduledDelivery

_STOP = {"the","a","an","and","or","of","to","in","for","on","with","from","by","at","is","are","was","were","be","as","this","that"}


def _keywords(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", (text or "").lower()) if w not in _STOP]


def scan_signals(db: Session, *, hours: int = 24, limit: int = 25, actor: str = "api") -> dict:
    """Monitor the actual inbound feed corpus and surface repeated/recent topics."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 24 * 30)))
    rows = (db.query(ContentItem).filter(ContentItem.content_type == "feed_item", ContentItem.created_at >= cutoff)
            .order_by(ContentItem.created_at.desc()).limit(max(20, min(limit * 20, 1000))).all())
    freq = Counter(w for i in rows for w in set(_keywords(i.title + " " + i.summary)))
    signals = []
    for i in rows:
        kws = _keywords(i.title + " " + i.summary)
        score = sum(max(0, freq[k] - 1) for k in set(kws[:12]))
        age_h = max(0.0, (datetime.now(timezone.utc) - (i.created_at if i.created_at.tzinfo else i.created_at.replace(tzinfo=timezone.utc))).total_seconds()/3600)
        score = round(score + max(0, 24 - age_h) / 24, 3)
        signals.append({"content_id": i.id, "title": i.title, "source": i.source, "score": score,
                        "repeated_keywords": [k for k in kws if freq[k] > 1][:8], "created_at": i.created_at.isoformat()})
    signals.sort(key=lambda x: (-x["score"], x["title"].lower()))
    out = {"window_hours": hours, "items_scanned": len(rows), "signals": signals[:limit]}
    record_event(db, content_id=None, actor=f"{display_name('signal')} (run by {actor})", action="signal.monitor",
                 decision="complete", details={"hours": hours, "items_scanned": len(rows), "signals": len(out["signals"])})
    db.commit()
    return out


def schedule_delivery(db: Session, item: ContentItem, endpoint: FeedEndpoint, run_at: datetime, actor: str) -> ScheduledDelivery:
    if not evaluate(item).passed or item.state not in {"approved", "published"}:
        raise GateBlocked("content must pass Gate before it can be scheduled")
    if endpoint.direction not in {"outbound", "bidirectional"} or not endpoint.enabled:
        raise PolicyBlocked("destination is not enabled for outbound delivery")
    when = run_at if run_at.tzinfo else run_at.replace(tzinfo=timezone.utc)
    if when <= datetime.now(timezone.utc):
        raise ValueError("run_at must be in the future")
    row = ScheduledDelivery(id=str(uuid.uuid4()), content_id=item.id, endpoint_id=endpoint.id,
                            content_hash=governed_hash(item), run_at=when, status="scheduled", actor=actor)
    db.add(row)
    record_event(db, content_id=item.id, actor=f"{display_name('social')} (run by {actor})", action="social.schedule",
                 decision="scheduled", details={"schedule_id": row.id, "endpoint_id": endpoint.id,
                                                  "run_at": when.isoformat(), "content_hash": row.content_hash})
    db.commit()
    return row


def run_due_schedules(db: Session, *, actor: str = "worker", limit: int = 100) -> dict:
    now = datetime.now(timezone.utc)
    rows = (db.query(ScheduledDelivery).filter(ScheduledDelivery.status == "scheduled", ScheduledDelivery.run_at <= now)
            .order_by(ScheduledDelivery.run_at.asc()).limit(max(1, min(limit, 500))).all())
    sent = failed = stale = 0
    for row in rows:
        item, ep = db.get(ContentItem, row.content_id), db.get(FeedEndpoint, row.endpoint_id)
        if not item or not ep or governed_hash(item) != row.content_hash:
            row.status, row.error = "stale", "content or destination changed/missing before scheduled send"
            stale += 1
            db.add(row); db.commit(); continue
        try:
            result = push_content(db, item, ep, actor=f"schedule:{actor}")
        except Exception as exc:  # already gated/audited by push_content
            row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:500]
            failed += 1
        else:
            row.status, row.delivery_id, row.error = "sent", result.get("delivery_id", ""), ""
            sent += 1
        db.add(row); db.commit()
    return {"due": len(rows), "sent": sent, "failed": failed, "stale": stale}


def triage_message(msg: InboxMessage) -> dict:
    text = (msg.body or "").lower()
    if any(k in text for k in ["breach", "security", "lawsuit", "fraud", "threat", "urgent", "outage"]):
        priority = "high"
    else:
        priority = "normal"
    if any(k in text for k in ["journalist", "reporter", "interview", "press", "media"]): intent = "media"
    elif any(k in text for k in ["price", "pricing", "buy", "purchase", "demo"]): intent = "commercial"
    elif any(k in text for k in ["complaint", "angry", "refund", "bad", "broken"]): intent = "complaint"
    elif any(k in text for k in ["help", "support", "issue", "problem"]): intent = "support"
    else: intent = "general"
    draft = "Thank you for reaching out. We have received your message and are routing it to the appropriate team."
    if intent == "media": draft = "Thank you for reaching out. We have received your media request and are routing it to the communications team."
    msg.priority, msg.intent, msg.response_draft, msg.state = priority, intent, draft, "triaged"
    return {"id": msg.id, "priority": priority, "intent": intent, "response_draft": draft, "state": msg.state}
