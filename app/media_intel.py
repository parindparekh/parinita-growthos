"""Provider-neutral PR/media intelligence for Parinita GrowthOS.

GrowthOS does not pretend to own a Cision/Muck Rack-sized proprietary journalist corpus.
Instead it normalizes licensed/provider data into contacts + coverage, ranks targets using
transparent evidence, and keeps source/provider attribution intact.
"""
from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from .audit import record_event
from .models import ContentItem, MediaContact, MediaCoverage

_STOP = {"the","a","an","and","or","of","to","in","for","on","with","from","by","at","is","are","was","were","be","as","this","that"}


def _kw(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", (text or "").lower()) if w not in _STOP]


def _score(v) -> float:
    try:
        return float(Decimal(str(v)))
    except (InvalidOperation, ValueError, TypeError):
        return 0.0


def upsert_contact(db: Session, data: dict, actor: str) -> tuple[MediaContact, bool]:
    provider, external = str(data["provider"]), str(data["external_id"])
    row = db.query(MediaContact).filter(MediaContact.provider == provider, MediaContact.external_id == external).first()
    created = row is None
    if row is None:
        row = MediaContact(id=str(data.get("id") or uuid.uuid4()), provider=provider, external_id=external,
                           name=str(data.get("name") or "Unknown"))
    for f in ("name", "outlet", "beat", "email", "profile_url", "location"):
        if f in data and data[f] is not None:
            setattr(row, f, str(data[f])[:2000 if f == "profile_url" else 500])
    if "influence_score" in data:
        row.influence_score = str(data.get("influence_score") or 0)
    row.metadata_json = json.dumps(data.get("metadata") or {}, ensure_ascii=False)
    db.add(row)
    record_event(db, content_id=None, actor=actor, action="media.contact.upsert", decision="created" if created else "updated",
                 details={"contact_id": row.id, "provider": provider, "external_id": external, "outlet": row.outlet})
    return row, created


def upsert_coverage(db: Session, data: dict, actor: str) -> tuple[MediaCoverage, bool]:
    provider, external = str(data["provider"]), str(data["external_id"])
    row = db.query(MediaCoverage).filter(MediaCoverage.provider == provider, MediaCoverage.external_id == external).first()
    created = row is None
    if row is None:
        row = MediaCoverage(id=str(data.get("id") or uuid.uuid4()), provider=provider, external_id=external,
                            title=str(data.get("title") or "Untitled")[:500])
    for f in ("title", "url", "outlet", "author", "body", "sentiment", "content_id"):
        if f in data and data[f] is not None:
            setattr(row, f, str(data[f])[:2000 if f == "url" else None])
    row.topics_json = json.dumps([str(x) for x in (data.get("topics") or [])][:100], ensure_ascii=False)
    row.metadata_json = json.dumps(data.get("metadata") or {}, ensure_ascii=False)
    if data.get("published_at"):
        p = data["published_at"]
        row.published_at = p if isinstance(p, datetime) else datetime.fromisoformat(str(p).replace("Z", "+00:00"))
    db.add(row)
    record_event(db, content_id=row.content_id, actor=actor, action="media.coverage.upsert", decision="created" if created else "updated",
                 details={"coverage_id": row.id, "provider": provider, "external_id": external, "outlet": row.outlet, "url": row.url})
    return row, created


def rank_targets(db: Session, item: ContentItem, limit: int = 20) -> list[dict]:
    """Rank available contacts by transparent topic/beat + coverage overlap. No hidden 'AI score'."""
    text = " ".join([item.title, item.summary or "", item.body[:3000]])
    item_terms = set(_kw(text))
    contacts = db.query(MediaContact).all()
    recent = datetime.now(timezone.utc) - timedelta(days=180)
    coverage = db.query(MediaCoverage).filter(MediaCoverage.created_at >= recent).all()
    by_author = Counter(c.author.lower() for c in coverage if c.author)
    by_outlet = Counter(c.outlet.lower() for c in coverage if c.outlet)
    out = []
    for c in contacts:
        target_terms = set(_kw(" ".join([c.beat or "", c.outlet or "", c.name or ""])))
        overlap = sorted(item_terms & target_terms)
        lexical = min(1.0, len(overlap) / 5.0)
        activity = min(1.0, (by_author[c.name.lower()] + by_outlet[c.outlet.lower()]) / 10.0)
        influence = max(0.0, min(1.0, _score(c.influence_score)))
        score = round(0.55 * lexical + 0.25 * influence + 0.20 * activity, 4)
        out.append({"contact_id": c.id, "name": c.name, "outlet": c.outlet, "beat": c.beat,
                    "provider": c.provider, "profile_url": c.profile_url, "score": score,
                    "matched_terms": overlap[:12], "basis": {"topic_overlap": lexical, "influence": influence, "recent_activity": activity}})
    out.sort(key=lambda r: (-r["score"], r["outlet"].lower(), r["name"].lower()))
    return out[:max(1, min(limit, 100))]


def coverage_summary(db: Session, days: int = 30) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))
    rows = db.query(MediaCoverage).filter(MediaCoverage.created_at >= cutoff).all()
    outlets = Counter(r.outlet for r in rows if r.outlet)
    authors = Counter(r.author for r in rows if r.author)
    topics = Counter(t for r in rows for t in json.loads(r.topics_json or "[]"))
    return {"days": days, "coverage": len(rows),
            "top_outlets": [{"outlet": k, "items": v} for k, v in outlets.most_common(20)],
            "top_authors": [{"author": k, "items": v} for k, v in authors.most_common(20)],
            "top_topics": [{"topic": k, "items": v} for k, v in topics.most_common(20)]}
