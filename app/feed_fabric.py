"""Parinita Feed Fabric: ingest -> canonical envelope -> render / push."""
from .agent_names import display_name
import hashlib
import json
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from defusedxml import ElementTree as SafeET
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .adapters import REGISTRY
from .audit import record_event
from .config import settings
from .content import create_content, public_projection
from .chrysalis import ensure_before_publish
from .gate import HIGH_RISK, evaluate
from .models import ContentItem, Delivery, FeedEndpoint
from .netguard import clean_headers, safe_get, secret_from_env
from .schemas import ContentCreate

INGEST_PROTOCOLS = {"rss", "atom", "jsonfeed"}
RENDER_PROTOCOLS = {"rss", "atom", "jsonfeed", "podcast_rss"}
DEFAULT_PUBLIC_CLASSES = ["general", "pr", "social"]
ARTIFACT_KEYS = {"audio_url", "audio_type", "audio_bytes", "audio_duration", "vaak"}  # what an adapter may add to metadata  # high-risk content never reaches a feed by default

ATOM_NS = "http://www.w3.org/2005/Atom"
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("itunes", ITUNES_NS)

_XML_INVALID = re.compile("[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")


class GateBlocked(PermissionError):
    pass


class PolicyBlocked(PermissionError):
    pass


def _x(s) -> str:
    """Strip characters that are illegal in XML 1.0 (they would make the whole feed unparseable)."""
    return _XML_INVALID.sub("", str(s or ""))


def _utc(dt) -> datetime:
    dt = dt or datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _cfg(endpoint: FeedEndpoint) -> dict:
    try:
        c = json.loads(endpoint.config_json or "{}")
        return c if isinstance(c, dict) else {}
    except ValueError:
        return {}


def _is_web_url(u: str) -> bool:
    return bool(re.match(r"^https?://", u or "", re.I))


# --------------------------------------------------------------------------- ingest
def _parse_entries(endpoint: FeedEndpoint, raw: bytes) -> list[dict]:
    if endpoint.protocol == "jsonfeed":
        data = json.loads(raw)
        return [{"id": e.get("id") or e.get("url") or "", "title": e.get("title") or "",
                 "body": e.get("content_text") or e.get("content_html") or e.get("summary") or "",
                 "summary": e.get("summary") or "", "link": e.get("url") or "", "published": e.get("date_published") or ""}
                for e in (data.get("items") or []) if isinstance(e, dict)]
    root = SafeET.fromstring(raw)  # defusedxml: no entity expansion, no external entities, no DTD retrieval
    entries = []
    if root.tag.endswith("}feed") or root.tag == "feed":
        ns = {"a": ATOM_NS}
        for node in root.findall("a:entry", ns):
            links = node.findall("a:link", ns)
            link = next((l for l in links if l.attrib.get("rel", "alternate") == "alternate"), links[0] if links else None)
            summary = (node.findtext("a:summary", default="", namespaces=ns) or "").strip()
            body = (node.findtext("a:content", default="", namespaces=ns) or "").strip() or summary
            entries.append({"id": (node.findtext("a:id", default="", namespaces=ns) or "").strip(),
                            "title": (node.findtext("a:title", default="", namespaces=ns) or "").strip(),
                            "body": body, "summary": summary or body[:1000],
                            "link": link.attrib.get("href", "") if link is not None else "",
                            "published": (node.findtext("a:published", default="", namespaces=ns)
                                          or node.findtext("a:updated", default="", namespaces=ns) or "").strip()})
    else:
        channel = root.find("channel")
        for node in (channel.findall("item") if channel is not None else root.findall(".//item")):
            desc = (node.findtext("description") or "").strip()
            body = (node.findtext(f"{{{CONTENT_NS}}}encoded") or "").strip() or desc
            entries.append({"id": (node.findtext("guid") or node.findtext("link") or "").strip(),
                            "title": (node.findtext("title") or "").strip(), "body": body, "summary": desc[:1000] or body[:1000],
                            "link": (node.findtext("link") or "").strip(), "published": (node.findtext("pubDate") or "").strip()})
    return entries


def ingest_endpoint(db: Session, endpoint: FeedEndpoint, actor: str = "worker") -> dict:
    if endpoint.protocol not in INGEST_PROTOCOLS:
        raise ValueError("endpoint is not an ingestible feed protocol")
    if endpoint.direction not in {"inbound", "bidirectional"}:
        raise ValueError("endpoint is not an inbound feed")
    if not endpoint.url:
        raise ValueError("endpoint URL is required")
    endpoint_id = endpoint.id
    try:
        cfg = _cfg(endpoint)
        headers = clean_headers(cfg.get("headers"))
        if cfg.get("bearer_token_env"):
            token = secret_from_env(cfg["bearer_token_env"])
            if not token:
                raise ValueError(f"secret {cfg['bearer_token_env']} is not set")
            headers["Authorization"] = "Bearer " + token
        entries = _parse_entries(endpoint, safe_get(endpoint.url, headers))
        truncated = max(0, len(entries) - settings.max_feed_entries)
        created, seen = [], set()
        for e in entries[: settings.max_feed_entries]:
            # Stable identity. Items with no guid/link fall back to a content fingerprint,
            # never a random id (which would duplicate the item on every poll).
            external = str(e["id"] or e["link"] or "fp:" + hashlib.sha256(
                f"{e['title']}\n{e['published']}\n{e['body'][:2000]}".encode()).hexdigest())
            cid = str(uuid.uuid5(uuid.NAMESPACE_URL, endpoint_id + ":" + external))
            if cid in seen or db.get(ContentItem, cid):
                continue
            seen.add(cid)
            link = e["link"] if _is_web_url(e["link"]) else ""
            item = create_content(db, ContentCreate(
                id=cid, content_type="feed_item", title=(e["title"] or "Untitled")[:500], body=e["body"] or "",
                summary=(e["summary"] or "")[:1000], source=(link or endpoint.url)[:1000],
                metadata={"feed_endpoint_id": endpoint_id, "external_id": external[:500], "published": e["published"]}),
                created_by=f"feed:{endpoint.slug}")
            created.append(item.id)
        endpoint.last_sync_at = datetime.now(timezone.utc)
        endpoint.last_status, endpoint.last_error = "ok", ""
        db.add(endpoint)
        record_event(db, content_id=None, actor=f"{display_name('feed')} (run by {actor})", action="feed.ingest", decision="success",
                     details={"endpoint_id": endpoint_id, "created": len(created), "entries": len(entries), "truncated": truncated})
        db.commit()
        return {"endpoint_id": endpoint_id, "created": created, "count": len(created), "truncated": truncated}
    except Exception as exc:
        # Leave the session usable, record the failure where an operator can see it, then surface it.
        db.rollback()
        ep = db.get(FeedEndpoint, endpoint_id)
        if ep is not None:
            ep.last_sync_at = datetime.now(timezone.utc)  # back off for one poll interval
            ep.last_status, ep.last_error = "error", f"{type(exc).__name__}: {exc}"[:1000]
            record_event(db, content_id=None, actor=f"{display_name('feed')} (run by {actor})", action="feed.ingest",
                         decision="failure", details={"endpoint_id": endpoint_id, "error": ep.last_error})
            db.commit()
        raise


# --------------------------------------------------------------------------- render
def allowed_classes(cfg: dict) -> list[str]:
    c = cfg.get("classifications") or ([cfg["classification"]] if cfg.get("classification") else DEFAULT_PUBLIC_CLASSES)
    return [str(x) for x in (c if isinstance(c, list) else [c])]


def _channel_items(db: Session, endpoint: FeedEndpoint) -> list[ContentItem]:
    """Items eligible for one rendered feed. An item appears only if the endpoint's routing rules
    select it AND it still passes the gate right now (defence in depth against stale state)."""
    cfg = _cfg(endpoint)
    try:
        limit = max(1, min(int(cfg.get("limit", 50)), 200))
    except (TypeError, ValueError):
        limit = 50
    q = db.query(ContentItem).filter(ContentItem.state.in_(["approved", "published"]),
                                     ContentItem.classification.in_(allowed_classes(cfg)))
    if cfg.get("campaign_id"):
        q = q.filter(ContentItem.campaign_id == str(cfg["campaign_id"]))
    if cfg.get("content_types"):
        q = q.filter(ContentItem.content_type.in_([str(t) for t in cfg["content_types"]]))
    elif not cfg.get("include_ingested"):
        q = q.filter(ContentItem.content_type != "feed_item")  # do not re-syndicate third-party items by default
    podcast = endpoint.protocol == "podcast_rss"
    out = []
    for i in q.order_by(ContentItem.created_at.desc()).limit(limit * 4 if podcast else limit).all():
        if podcast and not _is_web_url(json.loads(i.metadata_json or "{}").get("audio_url", "")):
            continue  # a podcast feed carries episodes only
        if evaluate(i).passed:
            out.append(i)
        if len(out) >= limit:
            break
    return out


def _item_link(i: ContentItem, home: str) -> str:
    return i.source if _is_web_url(i.source) else home


def render_feed(db: Session, endpoint: FeedEndpoint) -> tuple[str, str]:
    items = _channel_items(db, endpoint)
    cfg = _cfg(endpoint)
    title = str(cfg.get("title", endpoint.name))
    home = str(cfg.get("home_page_url", settings.public_base_url))
    desc = str(cfg.get("description", "Parinita GrowthOS feed"))
    author = str(cfg.get("author", settings.app_name))
    lang = str(cfg.get("language", "en-US"))
    feed_url = f"{settings.public_base_url.rstrip('/')}/feeds/{endpoint.slug}"
    newest = max((_utc(i.updated_at) for i in items), default=_utc(endpoint.created_at))

    if endpoint.protocol == "jsonfeed":
        doc_items = []
        for i in items:
            d = {"id": i.id, "title": i.title, "content_text": i.body, "date_published": _utc(i.created_at).isoformat(),
                 "date_modified": _utc(i.updated_at).isoformat(), "language": i.locale}
            if i.summary:
                d["summary"] = i.summary
            if _is_web_url(i.source):
                d["url"] = i.source  # only real URLs; never a link to a route that does not exist
            if _is_web_url(i.cta_url):
                d["external_url"] = i.cta_url
            doc_items.append(d)
        doc = {"version": "https://jsonfeed.org/version/1.1", "title": title, "home_page_url": home, "feed_url": feed_url,
               "description": desc, "language": lang, "authors": [{"name": author}], "items": doc_items}
        return json.dumps(doc, ensure_ascii=False, indent=2), "application/feed+json"

    if endpoint.protocol == "atom":
        # Plain tag names + an explicit default xmlns: thread-safe, no global namespace registry changes.
        feed = ET.Element("feed", {"xmlns": ATOM_NS})
        ET.SubElement(feed, "id").text = feed_url
        ET.SubElement(feed, "title").text = _x(title)
        ET.SubElement(feed, "updated").text = newest.isoformat()
        ET.SubElement(ET.SubElement(feed, "author"), "name").text = _x(author)
        ET.SubElement(feed, "link", {"href": feed_url, "rel": "self", "type": "application/atom+xml"})
        ET.SubElement(feed, "link", {"href": home, "rel": "alternate"})
        for i in items:
            e = ET.SubElement(feed, "entry")
            ET.SubElement(e, "id").text = f"urn:growthos:{_x(i.id)}"
            ET.SubElement(e, "title").text = _x(i.title)
            ET.SubElement(e, "updated").text = _utc(i.updated_at).isoformat()
            ET.SubElement(e, "published").text = _utc(i.created_at).isoformat()
            ET.SubElement(e, "summary").text = _x(i.summary or i.body[:500])
            ET.SubElement(e, "content", {"type": "text"}).text = _x(i.body)
            ET.SubElement(e, "link", {"href": _item_link(i, home), "rel": "alternate"})
        return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(feed, encoding="unicode"), "application/atom+xml"

    podcast = endpoint.protocol == "podcast_rss"
    it = lambda t: f"{{{ITUNES_NS}}}{t}"  # noqa: E731
    rss = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = _x(title)
    ET.SubElement(ch, "link").text = home
    ET.SubElement(ch, "description").text = _x(desc)
    ET.SubElement(ch, "language").text = lang
    ET.SubElement(ch, "lastBuildDate").text = format_datetime(newest)
    ET.SubElement(ch, f"{{{ATOM_NS}}}link", {"href": feed_url, "rel": "self", "type": "application/rss+xml"})
    if podcast:
        # Directory-required channel tags. image/owner_email/category come from endpoint config.
        ET.SubElement(ch, it("author")).text = _x(author)
        ET.SubElement(ch, it("summary")).text = _x(desc)
        ET.SubElement(ch, it("explicit")).text = "true" if cfg.get("explicit") else "false"
        ET.SubElement(ch, it("type")).text = str(cfg.get("show_type", "episodic"))
        ET.SubElement(ch, it("category"), {"text": str(cfg.get("category", "Business"))})
        if _is_web_url(str(cfg.get("image", ""))):
            ET.SubElement(ch, it("image"), {"href": str(cfg["image"])})
        if cfg.get("owner_email"):
            owner = ET.SubElement(ch, it("owner"))
            ET.SubElement(owner, it("name")).text = _x(cfg.get("owner_name", author))
            ET.SubElement(owner, it("email")).text = _x(cfg["owner_email"])
    for i in items:
        meta = json.loads(i.metadata_json or "{}")
        node = ET.SubElement(ch, "item")
        ET.SubElement(node, "guid", {"isPermaLink": "false"}).text = _x(i.id)
        ET.SubElement(node, "title").text = _x(i.title)
        ET.SubElement(node, "link").text = _item_link(i, home)
        ET.SubElement(node, "description").text = _x(i.summary or i.body[:1000])
        ET.SubElement(node, "pubDate").text = format_datetime(_utc(i.created_at))
        if podcast:
            try:
                length = max(0, int(meta.get("audio_bytes", 0)))
            except (TypeError, ValueError):
                length = 0
            ET.SubElement(node, "enclosure", {"url": str(meta["audio_url"]), "length": str(length),
                                              "type": str(meta.get("audio_type", "audio/mpeg"))})
            if meta.get("audio_duration"):
                ET.SubElement(node, it("duration")).text = _x(meta["audio_duration"])
            ET.SubElement(node, it("explicit")).text = "true" if meta.get("explicit") else "false"
    return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(rss, encoding="unicode"), "application/rss+xml"


# --------------------------------------------------------------------------- push
def push_content(db: Session, item: ContentItem, endpoint: FeedEndpoint, actor: str = "api") -> dict:
    """Gate -> endpoint policy -> idempotent delivery -> audit. Every outcome is recorded."""
    cfg = _cfg(endpoint)
    feed_actor = f"{display_name('feed')} (run by {actor})"

    def refuse(exc: Exception, decision: str):
        record_event(db, content_id=item.id, actor=feed_actor, action="publish.push", decision=decision,
                     details={"endpoint_id": endpoint.id, "content_hash": item.content_hash, "reason": str(exc)[:500]})
        db.commit()
        raise exc

    adapter = REGISTRY.get(endpoint.protocol)
    if adapter is None:
        raise ValueError("rendered feeds are exposed through /feeds/{slug}; push needs a webhook, smtp or provider endpoint")
    if not endpoint.enabled:
        refuse(PolicyBlocked("destination is disabled"), "refused")
    if endpoint.direction not in {"outbound", "bidirectional"}:
        refuse(PolicyBlocked("endpoint is not an outbound destination"), "refused")
    if item.classification not in allowed_classes(cfg):
        refuse(PolicyBlocked(f"destination does not accept '{item.classification}' content "
                             f"(add it to config.classifications to opt in)"), "refused")
    gate = evaluate(item)
    if not gate.passed:
        refuse(GateBlocked("Hallucination Gate blocked publish: " + "; ".join(gate.blockers)), "blocked")

    # Chrysalis is the external trust anchor. For configured fail-closed classes, no side effect
    # may leave GrowthOS until the exact governed release version has a Chrysalis receipt.
    try:
        chrysalis_anchor = ensure_before_publish(db, item, actor=actor)
    except PermissionError as exc:
        refuse(GateBlocked(str(exc)), "blocked")
    except Exception as exc:
        # Non-required Chrysalis failures remain visible in the audit chain but do not block general content.
        if settings.chrysalis_fail_closed_all or (settings.chrysalis_fail_closed_high_risk and item.classification in HIGH_RISK):
            refuse(GateBlocked("Chrysalis attestation failed"), "blocked")
        chrysalis_anchor = None

    # Idempotency: one delivery per (content version, destination).
    content_hash = gate.checks["content_hash"]
    existing = db.query(Delivery).filter_by(content_id=item.id, endpoint_id=endpoint.id, content_hash=content_hash).first()
    if existing and existing.status == "sent":
        return {"status": "sent", "duplicate": True, "delivery_id": existing.id, "destination": endpoint.name}
    stale_after = timedelta(seconds=settings.http_timeout_seconds * max(1, settings.push_max_attempts) * 2 + 30)
    if existing and existing.status == "pending" and datetime.now(timezone.utc) - _utc(existing.updated_at) < stale_after:
        raise PolicyBlocked("a delivery of this content version to this destination is already in progress")
    if existing:
        delivery = existing
        delivery.status = "pending"
    else:
        delivery = Delivery(id=str(uuid.uuid4()), content_id=item.id, endpoint_id=endpoint.id,
                            content_hash=content_hash, status="pending", actor=actor)
    db.add(delivery)
    try:
        db.commit()  # claim the slot before any side effect leaves the process
    except IntegrityError:
        db.rollback()
        raise PolicyBlocked("a delivery of this content version to this destination is already in progress") from None

    payload = public_projection(item, include_derivatives=bool(cfg.get("include_derivatives")))
    try:
        result = adapter.send(payload, endpoint, cfg, delivery.id, resume=delivery.provider_id or "")
    except Exception as exc:  # adapters must not leave a delivery stuck in 'pending'
        from .adapters import DeliveryResult
        result = DeliveryResult(ok=False, detail=f"{type(exc).__name__}: {exc}"[:500])
        blocked_exc = exc if isinstance(exc, ValueError) else None
    else:
        blocked_exc = None

    from .netguard import redact_destination_error
    result.detail = redact_destination_error(result.detail, cfg)
    delivery.attempts = (delivery.attempts or 0) + result.attempts
    delivery.response_code = result.status_code
    delivery.provider_id = result.provider_id or delivery.provider_id or ""  # keep a resume point across failed attempts
    delivery.status, delivery.error = ("sent", "") if result.ok else ("failed", result.detail)
    if result.ok:
        if result.artifacts:
            # Metadata is not governed, so this does not create a new content version or disturb an approval.
            meta = json.loads(item.metadata_json or "{}")
            meta.update({k: v for k, v in result.artifacts.items() if k in ARTIFACT_KEYS})
            item.metadata_json = json.dumps(meta)
        if result.publishes:
            item.state = "published"
            item.published_at = item.published_at or datetime.now(timezone.utc)
        db.add(item)
    db.add(delivery)
    record_event(db, content_id=item.id, actor=feed_actor, action="publish.push",
                 decision="success" if result.ok else "failure",
                 details={"endpoint_id": endpoint.id, "protocol": endpoint.protocol, "delivery_id": delivery.id,
                          "content_hash": content_hash, "attempts": delivery.attempts,
                          "status_code": result.status_code, "error": delivery.error,
                          "chrysalis_anchor": chrysalis_anchor.chrysalis_ref if chrysalis_anchor else ""})
    db.commit()
    if not result.ok:
        if blocked_exc is not None:
            raise ValueError(result.detail) from None
        raise RuntimeError(f"delivery failed: {result.detail}")
    return {"status": "sent", "duplicate": False, "delivery_id": delivery.id, "destination": endpoint.name,
            "provider_id": delivery.provider_id, "published": result.publishes, "artifacts": result.artifacts or {},
            "status_code": result.status_code, "attempts": delivery.attempts, "detail": result.detail,
            "chrysalis_anchor": chrysalis_anchor.chrysalis_ref if chrysalis_anchor else ""}

