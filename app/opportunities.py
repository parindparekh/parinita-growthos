"""Ranked next-action queue from GrowthOS observation streams."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .aeo import visibility_summary
from .audit import record_event
from .media_intel import coverage_summary
from .models import InboxMessage, MediaCoverage, Opportunity, PerformanceEvent
from .performance import learn as performance_learn


def _fp(kind: str, title: str, refs: list[str]) -> str:
    raw = json.dumps([kind, title.strip().lower(), sorted(str(r) for r in refs)], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _put(db: Session, *, kind: str, title: str, summary: str, score: float, refs: list[str], recommendation: dict) -> Opportunity:
    fp = _fp(kind, title, refs)
    row = db.query(Opportunity).filter(Opportunity.fingerprint == fp).first()
    if row is None:
        row = Opportunity(id=str(uuid.uuid4()), fingerprint=fp, kind=kind, title=title[:500], status="new")
    row.summary = summary
    row.score = f"{max(0.0, min(100.0, score)):.4f}"
    row.source_refs_json = json.dumps(refs[:100], ensure_ascii=False)
    row.recommendation_json = json.dumps(recommendation, ensure_ascii=False)
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    return row


def refresh(db: Session, *, brand: str = "Parinita", days: int = 30, actor: str = "api") -> dict:
    """Fuse media, AEO, inbox and performance signals into ranked opportunities."""
    made: list[str] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))

    # Earned media / topic pressure.
    for c in db.query(MediaCoverage).filter(MediaCoverage.created_at >= cutoff).order_by(MediaCoverage.created_at.desc()).limit(100).all():
        refs = [c.url or f"media:{c.id}"]
        score = 55 + (15 if c.content_id else 0) + (10 if c.sentiment == "positive" else 0)
        row = _put(db, kind="earned-media", title=f"Review coverage: {c.title}",
                   summary=f"{c.outlet or 'Media'} coverage from {c.author or 'unknown author'} may create a follow-up, correction, amplification or AEO opportunity.",
                   score=score, refs=refs,
                   recommendation={"action": "review-coverage", "coverage_id": c.id, "outlet": c.outlet, "author": c.author})
        made.append(row.id)

    # High-priority community/media inbound.
    for m in db.query(InboxMessage).filter(InboxMessage.state.in_(["new", "triaged"]), InboxMessage.priority == "high").limit(100).all():
        row = _put(db, kind="engagement", title=f"High-priority inbound from {m.sender or m.provider}", summary=m.body[:700],
                   score=88 if m.intent == "media" else 82, refs=[f"inbox:{m.id}"],
                   recommendation={"action": "human-response", "message_id": m.id, "intent": m.intent})
        made.append(row.id)

    # AEO visibility gaps.
    aeo = visibility_summary(db, brand, days)
    if aeo["probes"] and aeo["visibility_rate"] < 0.75:
        row = _put(db, kind="aeo", title=f"Improve {brand} answer-engine visibility",
                   summary=f"{brand} appeared in {aeo['mentions']} of {aeo['probes']} recorded answers in the last {days} days.",
                   score=round(60 + (1 - aeo["visibility_rate"]) * 30, 2), refs=[f"aeo:{brand}:{days}"],
                   recommendation={"action": "review-missing-prompts-and-earned-media", "visibility_rate": aeo["visibility_rate"],
                                   "top_citation_domains": aeo["top_citation_domains"][:10]})
        made.append(row.id)

    # Performance weak spots.
    perf = performance_learn(db, days=days)
    for i, action in enumerate(perf["actions"][:10]):
        if action.get("action") == "connect-performance-feed":
            score = 80
        else:
            score = 58 + max(0, 10 - i)
        row = _put(db, kind="performance", title=f"Performance: {action.get('action', 'review')}", summary=action.get("why", ""),
                   score=score, refs=[f"performance:{days}:{i}"], recommendation=action)
        made.append(row.id)

    record_event(db, content_id=None, actor=f"Parinita Signal Agent (run by {actor})", action="opportunity.refresh",
                 decision="complete", details={"brand": brand, "days": days, "opportunities_touched": len(set(made)),
                                                "coverage_summary": coverage_summary(db, days)})
    db.commit()
    rows = db.query(Opportunity).filter(Opportunity.status == "new").all()
    ranked = sorted(rows, key=lambda r: (-float(r.score or 0), r.created_at))
    return {"brand": brand, "days": days, "opportunities": [view(r) for r in ranked[:100]]}


def view(r: Opportunity) -> dict:
    return {"id": r.id, "kind": r.kind, "title": r.title, "summary": r.summary, "score": float(r.score or 0),
            "status": r.status, "source_refs": json.loads(r.source_refs_json or "[]"),
            "recommendation": json.loads(r.recommendation_json or "{}"), "created_at": r.created_at, "updated_at": r.updated_at}
