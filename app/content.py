import hashlib
import json
import uuid

from sqlalchemy.orm import Session

from .models import ContentItem
from .schemas import ContentCreate, ContentUpdate

# Fields a reviewer actually approves. State, approval, timestamps and agent scratch
# metadata are deliberately excluded so the hash is stable until the content changes.
GOVERNED_FIELDS = ("content_type", "title", "body", "summary", "locale", "source",
                   "classification", "cta_url", "campaign_id")


def compute_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


def governed_hash(item: ContentItem) -> str:
    data = {f: getattr(item, f) for f in GOVERNED_FIELDS}
    data["claims"] = json.loads(item.claims_json or "[]")
    return compute_hash(data)


def create_content(db: Session, payload: ContentCreate, created_by: str = "") -> ContentItem:
    """Adds and flushes; the caller commits (together with its audit event)."""
    item = ContentItem(
        id=payload.id or str(uuid.uuid4()), campaign_id=payload.campaign_id, content_type=payload.content_type,
        title=payload.title, body=payload.body, summary=payload.summary, locale=payload.locale,
        source=payload.source, classification=payload.classification, cta_url=payload.cta_url,
        claims_json=json.dumps([c.model_dump(mode="json") for c in payload.claims]),
        metadata_json=json.dumps(payload.metadata), approval_json="{}", dispositions_json="{}", state="draft", created_by=created_by, updated_by=created_by,
    )
    item.content_hash = governed_hash(item)
    db.add(item)
    db.flush()
    return item


def update_content(item: ContentItem, patch: ContentUpdate) -> list[str]:
    """Apply a partial update. Returns the governed fields that changed."""
    data = patch.model_dump(exclude_unset=True, mode="json")
    changed = []
    for f in GOVERNED_FIELDS:
        if f in data and data[f] is not None and data[f] != getattr(item, f):
            setattr(item, f, data[f]); changed.append(f)
    if "campaign_id" in data and data["campaign_id"] is None and item.campaign_id is not None:
        item.campaign_id = None; changed.append("campaign_id")
    if data.get("claims") is not None:
        new = json.dumps(data["claims"])
        if json.loads(new) != json.loads(item.claims_json or "[]"):
            item.claims_json = new; changed.append("claims")
    if data.get("metadata") is not None:
        # Caller metadata is merged; agent output lives under a reserved key and is preserved.
        meta = json.loads(item.metadata_json or "{}")
        keep = {k: meta[k] for k in ("agent_history", "vaak", "editorial_review") if k in meta}
        meta = dict(data["metadata"])
        meta.update(keep)
        item.metadata_json = json.dumps(meta)
    if changed:
        item.content_hash = governed_hash(item)
        item.state = "draft"  # withdraws it from rendered feeds until it passes the gate again
    return changed


def serialize(item: ContentItem) -> dict:
    """Full internal view (authenticated API)."""
    return {
        "id": item.id, "campaign_id": item.campaign_id, "content_type": item.content_type,
        "title": item.title, "body": item.body, "summary": item.summary, "locale": item.locale,
        "source": item.source, "classification": item.classification, "cta_url": item.cta_url,
        "claims": json.loads(item.claims_json or "[]"), "metadata": json.loads(item.metadata_json or "{}"),
        "state": item.state, "approval": json.loads(item.approval_json or "{}"), "content_hash": item.content_hash,
        "dispositions": json.loads(item.dispositions_json or "{}"),
        "created_by": item.created_by, "updated_by": item.updated_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }


def public_projection(item: ContentItem, *, include_derivatives: bool = False) -> dict:
    """What leaves the system on push. No approval notes, no agent scratch data, no internal metadata."""
    meta = json.loads(item.metadata_json or "{}")
    out = {
        "id": item.id, "campaign_id": item.campaign_id, "content_type": item.content_type,
        "title": item.title, "body": item.body, "summary": item.summary, "locale": item.locale,
        "source": item.source, "classification": item.classification, "cta_url": item.cta_url,
        "claims": json.loads(item.claims_json or "[]"), "content_hash": item.content_hash,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
    if isinstance(meta.get("public"), dict):
        out["metadata"] = meta["public"]
    media = {k: meta[k] for k in ("audio_url", "audio_type", "audio_bytes", "audio_duration") if meta.get(k)}
    if media:
        out["media"] = media
    # Channel copy for provider adapters: only derivatives generated from exactly this version. Amplify's generic
    # derivatives first; a channel agent's family-specific copy (v1.7) overrides them for its protocols.
    history = [h for h in meta.get("agent_history", []) if h.get("derived_from_hash") == item.content_hash]
    out["channel_copy"] = {p["channel"]: p["copy"] for h in history if h.get("agent") == "amplify"
                           for p in h.get("result", {}).get("derivatives", []) if isinstance(p, dict) and p.get("copy")}
    for h in history:
        r = h.get("result") or {}
        if isinstance(r.get("copy"), dict) and r.get("family"):
            out["channel_copy"].update({str(k): str(v) for k, v in r["copy"].items() if isinstance(v, str) and v.strip()})
    if include_derivatives:
        # Only derivatives generated from exactly this content version are eligible to leave.
        out["derivatives"] = {h["agent"]: h["result"] for h in meta.get("agent_history", [])
                              if h.get("derived_from_hash") == item.content_hash
                              and h.get("agent") in {"signal", "media", "podcast", "amplify"}}
    return out
