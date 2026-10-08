"""Polling worker for inbound feeds. One session per endpoint so a failure cannot poison the rest."""
import logging
import time
from datetime import datetime, timezone

from .config import settings
from .chrysalis import anchor_audit_head
from .agent_ops import run_due_schedules
from .db import SessionLocal
from .feed_fabric import INGEST_PROTOCOLS, ingest_endpoint
from .migrate import schema_ready
from .models import FeedEndpoint, ChrysalisAnchor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("growthos.worker")


def _due(ep: FeedEndpoint) -> bool:
    if ep.last_sync_at is None:
        return True
    last = ep.last_sync_at if ep.last_sync_at.tzinfo else ep.last_sync_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() >= ep.poll_seconds


def run_once() -> dict:
    with SessionLocal() as db:
        ids = [e.id for e in db.query(FeedEndpoint).filter(
            FeedEndpoint.enabled.is_(True), FeedEndpoint.direction.in_(["inbound", "bidirectional"])).all()
            if e.protocol in INGEST_PROTOCOLS and _due(e)]
    stats = {"synced": 0, "failed": 0}
    for eid in ids:
        with SessionLocal() as db:
            ep = db.get(FeedEndpoint, eid)
            if ep is None or not ep.enabled:
                continue
            try:
                r = ingest_endpoint(db, ep, actor="worker")
                stats["synced"] += 1
                log.info("feed %s synced: %s new", eid, r["count"])
            except Exception as exc:  # noqa: BLE001 - already recorded on the endpoint + audit log
                stats["failed"] += 1
                log.warning("feed %s failed: %s", eid, exc)
    with SessionLocal() as db:
        try:
            sched = run_due_schedules(db, actor="worker")
            if sched["due"]:
                log.info("scheduled deliveries: %s sent, %s failed, %s stale", sched["sent"], sched["failed"], sched["stale"])
        except Exception:  # noqa: BLE001
            log.exception("scheduled delivery cycle failed")
    if settings.chrysalis_enabled:
        with SessionLocal() as db:
            try:
                last = (db.query(ChrysalisAnchor).filter(ChrysalisAnchor.anchor_type == "audit_head",
                                                        ChrysalisAnchor.status == "anchored")
                        .order_by(ChrysalisAnchor.anchored_at.desc()).first())
                last_at = last.anchored_at if last else None
                if last_at is None or (datetime.now(timezone.utc) - (last_at if last_at.tzinfo else last_at.replace(tzinfo=timezone.utc))).total_seconds() >= max(60, settings.chrysalis_anchor_interval_seconds):
                    row = anchor_audit_head(db, actor="worker")
                    log.info("Chrysalis audit anchor: %s (%s)", row.chrysalis_ref, row.status)
            except Exception:  # noqa: BLE001
                log.exception("Chrysalis audit anchoring failed")
    return stats


def main():
    settings.validate_runtime()
    # The API owns schema creation; wait for it instead of racing it.
    while not schema_ready():
        log.info("waiting for API to initialise the schema")
        time.sleep(3)
    log.info("worker started; poll interval %ss", max(30, settings.feed_poll_seconds))
    while True:
        try:
            run_once()
        except Exception:  # noqa: BLE001 - keep the loop alive across transient DB errors
            log.exception("worker cycle failed")
        time.sleep(max(30, settings.feed_poll_seconds))


if __name__ == "__main__":
    main()
