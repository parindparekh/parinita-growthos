"""Hash-chained, append-only audit log.

record_event() never commits: the caller commits the event in the same transaction
as the state change it describes, so the two cannot diverge.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import AuditEvent

_CHAIN_LOCK = 727274


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash_v2(ev_id, ts, content_id, actor, action, decision, details_c, prev_hash) -> str:
    payload = {"v": 2, "event_id": ev_id, "ts": ts, "content_id": content_id, "actor": actor,
               "action": action, "decision": decision, "details": details_c, "prev_hash": prev_hash}
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def _hash_v1(ev_id, content_id, actor, action, decision, details_json, prev_hash) -> str:
    """v1.0 scheme (no timestamp). Kept so chains written by v1.0 still verify."""
    payload = {"event_id": ev_id, "content_id": content_id, "actor": actor, "action": action,
               "decision": decision, "details": json.loads(details_json or "{}"), "prev_hash": prev_hash}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_event(db: Session, *, content_id: str | None, actor: str, action: str,
                 decision: str = "", details: dict | None = None) -> AuditEvent:
    if db.get_bind().dialect.name == "postgresql":
        # One chain writer at a time; released at commit/rollback.
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK})
    db.flush()
    previous = db.query(AuditEvent).order_by(AuditEvent.seq.desc()).first()
    prev_hash = previous.event_hash if previous else ""
    ev_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    details_c = canonical(details or {})
    ev = AuditEvent(event_id=ev_id, content_id=content_id, actor=actor[:100], action=action, decision=(decision or "")[:30],
                    details_json=details_c, prev_hash=prev_hash, ts=ts, hash_version=2,
                    event_hash=_hash_v2(ev_id, ts, content_id, actor[:100], action, (decision or "")[:30], details_c, prev_hash))
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session, batch: int = 1000) -> dict:
    """Recompute every hash and link. Returns the head hash so it can be anchored externally."""
    count, prev_hash, last_seq = 0, "", 0
    while True:
        rows = db.query(AuditEvent).filter(AuditEvent.seq > last_seq).order_by(AuditEvent.seq.asc()).limit(batch).all()
        if not rows:
            break
        for e in rows:
            if e.prev_hash != prev_hash:
                return {"ok": False, "events": count, "break_at_seq": e.seq, "reason": "prev_hash does not match preceding event"}
            if (e.hash_version or 1) >= 2:
                expected = _hash_v2(e.event_id, e.ts, e.content_id, e.actor, e.action, e.decision, e.details_json, e.prev_hash)
            else:
                expected = _hash_v1(e.event_id, e.content_id, e.actor, e.action, e.decision, e.details_json, e.prev_hash)
            if expected != e.event_hash:
                return {"ok": False, "events": count, "break_at_seq": e.seq, "reason": "event content does not match its hash"}
            prev_hash, last_seq, count = e.event_hash, e.seq, count + 1
    return {"ok": True, "events": count, "head_seq": last_seq, "head_hash": prev_hash}
