import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func
from sqlalchemy import text
from sqlalchemy.orm import Session

from .agents import AGENT_MANIFEST, PIPELINE, run_agent
from .agent_ops import scan_signals, schedule_delivery, triage_message
from .media_intel import upsert_contact, upsert_coverage, rank_targets, coverage_summary
from .opportunities import refresh as refresh_opportunities, view as opportunity_view
from .claim_graph import graph as claim_graph, observe_coverage
from .chrysalis import anchor_audit_head, anchor_release, view as chrysalis_view
from .aeo import (claim_manifest, jsonld as aeo_jsonld, visibility_summary as aeo_visibility,
                  recommendations as aeo_recommendations, run_rest_probe)
from .claims import extract_candidates
from .audit import record_event, verify_chain
from .config import settings
from .content import create_content, governed_hash, serialize, update_content
from .db import get_db
from .feed_fabric import (INGEST_PROTOCOLS, RENDER_PROTOCOLS, GateBlocked, PolicyBlocked, ingest_endpoint,
                          push_content, render_feed)
from . import sso
from .gate import HIGH_RISK, account, dispositions_hash, evaluate
from .migrate import init_db
from .models import (AEOProbe, AEOQuery, AuditEvent, Campaign, ContentItem, Delivery, FeedEndpoint,
                     InboxMessage, PerformanceEvent, ScheduledDelivery, MediaContact, MediaCoverage,
                     Opportunity, ClaimObservation, ChrysalisAnchor)
from .netguard import DestinationBlocked, validate_endpoint_config
from .performance import summarize as performance_summary, learn as performance_learn
from .rate_limit import middleware as rate_limit_middleware
from .schemas import (AEOProbeCreate, AEOProbeRun, AEOQueryCreate, AgentRunRequest, ApprovalRequest, CampaignCreate, ClaimAddRequest,
                      ClaimConfirmRequest, ContentCreate, ContentUpdate, DispositionRequest, FeedEndpointCreate,
                      FeedEndpointUpdate, InboxMessageCreate, InboxStateUpdate, PerformanceEventCreate, PublishRequest,
                      ScheduleCreate, MediaContactCreate, MediaCoverageCreate, OpportunityStateUpdate, ClaimObservationCreate)
from .security import Principal, authenticate, optional_principal, require_human, require_role

VERSION = "1.9.1"
STATIC = Path(__file__).parent / "static"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_runtime()  # refuses weak/default credentials in production
    init_db()
    yield


_docs = {} if settings.docs_on else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title="Parinita GrowthOS", version=VERSION, lifespan=lifespan,
              description="Evidence-governed PR + Social + Media + AEO + Growth operating system and Feed Fabric", **_docs)
app.middleware("http")(rate_limit_middleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith(("/console", "/auth")) or request.url.path == "/":
        # No inline script, no third-party origins: the console only ever talks to this API.
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; media-src 'self'; "
            "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        response.headers.setdefault("Cache-Control", "no-store")
    return response


from .mcp_server import router as mcp_router  # noqa: E402
app.include_router(mcp_router)
from .drafting import router as drafting_router  # noqa: E402
app.include_router(drafting_router)
from .connectors import router as connectors_router  # noqa: E402
app.include_router(connectors_router)


# ----------------------------------------------------------------------------- helpers
def _content(db: Session, content_id: str, lock: bool = False) -> ContentItem:
    # lock=True takes a row lock (PostgreSQL) for the rest of the transaction: every route that changes a release
    # uses it, so "run checks" and "edit" on the same release are serialised instead of interleaved.
    item = db.get(ContentItem, content_id, with_for_update=True) if lock else db.get(ContentItem, content_id)
    if not item:
        raise HTTPException(404, "content not found")
    return item


def _endpoint(db: Session, endpoint_id: str) -> FeedEndpoint:
    ep = db.get(FeedEndpoint, endpoint_id)
    if not ep:
        raise HTTPException(404, "feed endpoint not found")
    return ep


def _endpoint_view(e: FeedEndpoint) -> dict:
    out = {"id": e.id, "name": e.name, "slug": e.slug, "direction": e.direction, "protocol": e.protocol, "url": e.url,
           "channel": e.channel, "enabled": e.enabled, "poll_seconds": e.poll_seconds, "config": json.loads(e.config_json or "{}"),
           "last_sync_at": e.last_sync_at, "last_status": e.last_status, "last_error": e.last_error}
    if e.protocol in RENDER_PROTOCOLS and e.direction in {"outbound", "bidirectional"}:
        out["public_url"] = f"{settings.public_base_url.rstrip('/')}/feeds/{e.slug}"
    return out


def _needs_url(protocol: str, direction: str, config: dict | None = None) -> bool:
    if protocol in {"webhook", "rest_json", "mastodon", "wordpress", "mcp", "vaak", "lemmy", "shopify", "ghost", "matrix", "zulip"}:
        return True
    if protocol == "pr_wire":
        return (config or {}).get("mode", "api") == "api"
    return direction in {"inbound", "bidirectional"} and protocol in INGEST_PROTOCOLS


def _rebind_approval_to_dispositions(item: ContentItem, p: Principal) -> None:
    """A recorded approval binds the dispositions in force (v1.6.1). When the person changing a disposition holds the
    approver role, the approval follows the change (they could re-approve anyway); otherwise it goes stale, so an editor
    acting as waiver authority cannot convert an approved-but-blocked high-risk release into a releasable one on their own."""
    approval = json.loads(item.approval_json or "{}")
    if not approval.get("approved_by") or "dispositions_hash" not in approval:
        return
    if p.has("approver"):
        approval["dispositions_hash"] = dispositions_hash(item)
        if approval.get("approved_by") != p.name:
            approval["dispositions_rebound_by"] = p.name  # a second approver changed the waivers; the audit chain has the detail
        item.approval_json = json.dumps(approval)


def _waiver_dep():
    # Resolved per request so GATE_WAIVER_ROLE can differ by deployment.
    def dep(request: Request, p: Principal = Depends(authenticate)) -> Principal:
        return require_human(settings.gate_waiver_role)(p)
    return dep


# ----------------------------------------------------------------------------- public
@app.get("/", response_class=HTMLResponse)
def home():
    # Styles live in /console/landing.css: the CSP on this path is style-src 'self', so an inline <style> block would
    # be dropped by the browser (v1.6.0 shipped one and rendered unstyled).
    docs = "Developer API: <a href='/docs'>/docs</a> &nbsp; " if settings.docs_on else ""
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Parinita GrowthOS</title>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/console/landing.css'></head>"
            f"<body><h1>Parinita GrowthOS</h1><div class='tag'>PR + Social + Media + Growth + Feed Fabric &middot; v{VERSION}</div>"
            f"<div class='grid'><div class='card'><b>Canonical Content</b><p>Normalize once, publish everywhere.</p></div>"
            f"<div class='card'><b>Feed Fabric</b><p>RSS, Atom, JSON Feed, Podcast RSS, REST, webhooks and SMTP.</p></div>"
            f"<div class='card'><b>Governed Agents</b><p>Signal, PR, Media, Podcast, Social, Amplify, Engagement, Acquire, Feed, Claim, AEO, Performance, Gate and Rally.</p></div></div>"
            f"<p><a href='/console'>Open Growth Command</a> &nbsp; {docs}Health: <a href='/health'>/health</a></p></body></html>")


@app.get("/live")
def live():
    """Process liveness, independent of database availability."""
    return {"status": "alive"}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unreachable", "version": VERSION})
    return {"status": "ok", "product": "Parinita GrowthOS", "version": VERSION, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/feeds/{slug}")
def public_feed(slug: str, db: Session = Depends(get_db)):
    ep = db.query(FeedEndpoint).filter(FeedEndpoint.slug == slug, FeedEndpoint.enabled.is_(True)).first()
    if not ep or ep.protocol not in RENDER_PROTOCOLS or ep.direction not in {"outbound", "bidirectional"}:
        raise HTTPException(404, "feed not found")
    body, ctype = render_feed(db, ep)
    return Response(content=body, media_type=ctype, headers={"Cache-Control": "public, max-age=60"})


@app.get("/media/{content_id}/{name}")
def media(content_id: str, name: str, db: Session = Depends(get_db)):
    """Audio rendered through Vaak. Served only while the exact version it was rendered from is still clear:
    edit or block the release and its audio stops being served. High-risk classes are never served here."""
    import re
    from .adapters.vaak import media_filename
    from .feed_fabric import DEFAULT_PUBLIC_CLASSES
    if not settings.media_dir or not re.fullmatch(r"[0-9a-f]{12}\.wav", name):
        raise HTTPException(404, "not found")
    item = db.get(ContentItem, content_id)
    if (item is None or not item.content_hash.startswith(name[:12]) or item.state not in {"approved", "published"}
            or item.classification not in DEFAULT_PUBLIC_CLASSES or not evaluate(item).passed):
        raise HTTPException(404, "not found")
    path = Path(settings.media_dir) / media_filename(content_id, name[:12])
    if not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "public, max-age=300"})


# ----------------------------------------------------------------------------- console + SSO
@app.get("/console", include_in_schema=False)
def console():
    return FileResponse(STATIC / "console.html", media_type="text/html")


@app.get("/console/{asset}", include_in_schema=False)
def console_asset(asset: str):
    allowed = {"console.js": "text/javascript", "console.css": "text/css", "landing.css": "text/css",
               "newsreader.woff2": "font/woff2", "newsreader-italic.woff2": "font/woff2", "instrument-sans.woff2": "font/woff2"}
    if asset not in allowed:  # fixed allowlist: no path traversal, no directory listing
        raise HTTPException(404, "not found")
    return FileResponse(STATIC / asset, media_type=allowed[asset])


@app.get("/auth/config")
def auth_config(p: Principal | None = Depends(optional_principal)):
    me = {"principal": p.name, "roles": sorted(p.roles), "source": p.source, "csrf": p.csrf} if p else None
    return {"sso": settings.sso_enabled, "sso_label": "Witness" if settings.is_witness else "your company account",
            "api_keys": bool(settings.parsed_keys()), "version": VERSION,
            "approvals_need_sso": settings.approvals_need_sso, "waiver_role": settings.gate_waiver_role, "me": me}


@app.get("/auth/login", include_in_schema=False)
def auth_login(next: str | None = None):
    if not settings.sso_enabled:
        raise HTTPException(404, "SSO is not configured")
    try:
        url, flow = sso.begin_login(next)
    except sso.SSOError as e:
        raise HTTPException(502, str(e))
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(sso.FLOW_COOKIE, flow, max_age=sso.FLOW_TTL, httponly=True, secure=settings.is_production,
                    samesite="lax", path="/auth")
    return resp


@app.get("/auth/callback", include_in_schema=False)
def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if not settings.sso_enabled:
        raise HTTPException(404, "SSO is not configured")
    if error or not code:
        raise HTTPException(400, f"sign-in was not completed: {error[:80] or 'no code returned'}")
    try:
        session, nxt = sso.complete_login(code, state, request.cookies.get(sso.FLOW_COOKIE, ""))
    except sso.SSOError as e:
        raise HTTPException(400, f"sign-in failed: {e}")
    resp = RedirectResponse(nxt, status_code=302)
    resp.delete_cookie(sso.FLOW_COOKIE, path="/auth", secure=settings.is_production, httponly=True, samesite="lax")
    resp.set_cookie(sso.session_cookie_name(), session, max_age=settings.session_ttl_seconds, httponly=True,
                    secure=settings.is_production, samesite="lax", path="/")
    return resp


@app.post("/auth/logout")
def auth_logout(p: Principal = Depends(authenticate)):
    resp = JSONResponse({"signed_out": True})
    # Same attributes as when it was set: a __Host- cookie can only be cleared by a Secure Set-Cookie.
    resp.delete_cookie(sso.session_cookie_name(), path="/", secure=settings.is_production, httponly=True, samesite="lax")
    return resp


@app.get("/auth/me")
def auth_me(p: Principal = Depends(authenticate)):
    return {"principal": p.name, "roles": sorted(p.roles), "source": p.source, "csrf": p.csrf}


# ----------------------------------------------------------------------------- identity / agents
@app.get("/v1/whoami")
def whoami(p: Principal = Depends(authenticate)):
    return {"principal": p.name, "roles": sorted(p.roles), "source": p.source}


@app.get("/v1/agents", dependencies=[Depends(authenticate)])
def agents():
    return AGENT_MANIFEST


@app.get("/v1/agents/signal/monitor")
def signal_monitor(hours: int = Query(24, ge=1, le=720), limit: int = Query(25, ge=1, le=200),
                   db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    return scan_signals(db, hours=hours, limit=limit, actor=p.name)


# ----------------------------------------------------------------------------- content
@app.post("/v1/content", status_code=201)
def add_content(payload: ContentCreate, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    if payload.id and db.get(ContentItem, payload.id):
        raise HTTPException(409, "content id already exists")
    if payload.campaign_id and not db.get(Campaign, payload.campaign_id):
        raise HTTPException(400, "campaign_id does not exist")
    item = create_content(db, payload, created_by=p.name)
    record_event(db, content_id=item.id, actor=p.name, action="content.create",
                 details={"type": item.content_type, "classification": item.classification, "content_hash": item.content_hash})
    db.commit()
    return serialize(item)


@app.get("/v1/content", dependencies=[Depends(authenticate)])
def list_content(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), state: str | None = None,
                 classification: str | None = None, campaign_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(ContentItem)
    if state:
        q = q.filter(ContentItem.state == state)
    if classification:
        q = q.filter(ContentItem.classification == classification)
    if campaign_id:
        q = q.filter(ContentItem.campaign_id == campaign_id)
    return [serialize(i) for i in q.order_by(ContentItem.created_at.desc()).offset(offset).limit(limit).all()]


@app.get("/v1/content/stats", dependencies=[Depends(authenticate)])
def content_stats(db: Session = Depends(get_db)):
    rows = db.query(ContentItem.state, func.count(ContentItem.id)).group_by(ContentItem.state).all()
    return {"by_state": {state: n for state, n in rows}}


@app.get("/v1/content/{content_id}/assertions", dependencies=[Depends(authenticate)])
def assertions(content_id: str, db: Session = Depends(get_db)):
    """Sentence ledger: what each sentence asserts and how it is accounted for."""
    item = _content(db, content_id)
    return {"content_hash": item.content_hash, "sentences": account(item)}


@app.put("/v1/content/{content_id}/assertions/{sentence_hash}/disposition")
def set_disposition(content_id: str, sentence_hash: str, req: DispositionRequest, db: Session = Depends(get_db),
                    p: Principal = Depends(_waiver_dep())):
    """Record that a sentence needs no evidence. Bound to the sentence text: editing the sentence voids it."""
    item = _content(db, content_id, lock=True)
    row = next((r for r in account(item) if r["hash"] == sentence_hash), None)
    if row is None:
        raise HTTPException(404, "no such sentence in the current version of this content")
    if row["status"] == "exempt":
        raise HTTPException(409, "this sentence needs no disposition")
    if settings.four_eyes and item.classification in HIGH_RISK and p.name in {item.created_by, item.updated_by}:
        raise HTTPException(403, "four-eyes rule: the author or last editor of high-risk content cannot waive its sentences")
    d = json.loads(item.dispositions_json or "{}")
    d[sentence_hash] = {"disposition": req.disposition, "note": req.note, "by": p.name,
                        "at": datetime.now(timezone.utc).isoformat(), "text": row["text"][:300]}
    item.dispositions_json = json.dumps(d)
    _rebind_approval_to_dispositions(item, p)
    if item.state in {"approved", "blocked"}:
        item.state = "draft"  # the gate must be re-run to pick the decision up
    db.add(item)
    record_event(db, content_id=item.id, actor=p.name, action="sentence.disposition", decision=req.disposition,
                 details={"sentence_hash": sentence_hash, "text": row["text"][:300], "note": req.note, "content_hash": item.content_hash})
    db.commit()
    return {"sentences": account(item)}


@app.delete("/v1/content/{content_id}/assertions/{sentence_hash}/disposition")
def clear_disposition(content_id: str, sentence_hash: str, db: Session = Depends(get_db), p: Principal = Depends(_waiver_dep())):
    item = _content(db, content_id, lock=True)
    d = json.loads(item.dispositions_json or "{}")
    if sentence_hash not in d:
        raise HTTPException(404, "no disposition recorded for this sentence")
    d.pop(sentence_hash)
    item.dispositions_json = json.dumps(d)
    _rebind_approval_to_dispositions(item, p)
    if item.state != "published":
        item.state = "draft"
    db.add(item)
    record_event(db, content_id=item.id, actor=p.name, action="sentence.disposition", decision="cleared",
                 details={"sentence_hash": sentence_hash, "content_hash": item.content_hash})
    db.commit()
    return {"sentences": account(item)}


@app.get("/v1/content/{content_id}", dependencies=[Depends(authenticate)])
def get_content(content_id: str, db: Session = Depends(get_db)):
    return serialize(_content(db, content_id))


@app.patch("/v1/content/{content_id}")
def edit_content(content_id: str, patch: ContentUpdate, db: Session = Depends(get_db),
                 p: Principal = Depends(require_role("editor"))):
    item = _content(db, content_id, lock=True)
    if patch.campaign_id and not db.get(Campaign, patch.campaign_id):
        raise HTTPException(400, "campaign_id does not exist")
    before = item.content_hash
    changed = update_content(item, patch)
    if changed:
        item.updated_by = p.name
    db.add(item)
    record_event(db, content_id=item.id, actor=p.name, action="content.update", decision="draft" if changed else "",
                 details={"changed": changed, "previous_hash": before, "content_hash": item.content_hash})
    db.commit()
    return serialize(item)


@app.post("/v1/content/{content_id}/agents/run")
def agent_run(content_id: str, req: AgentRunRequest, db: Session = Depends(get_db),
              p: Principal = Depends(require_role("editor"))):
    item = _content(db, content_id, lock=True)
    try:
        result = run_agent(db, item, req.agent, req.options, actor=p.name)
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    db.commit()
    return result


@app.post("/v1/content/{content_id}/pipeline")
def pipeline(content_id: str, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    item = _content(db, content_id, lock=True)
    results = {}
    try:
        for a in PIPELINE:
            results[a] = run_agent(db, item, a, {}, actor=p.name)
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    db.commit()  # the whole pipeline and its audit events land atomically
    return {"content_id": content_id, "state": item.state, "content_hash": item.content_hash, "results": results}


@app.get("/v1/content/{content_id}/gate", dependencies=[Depends(authenticate)])
def gate(content_id: str, db: Session = Depends(get_db)):
    return evaluate(_content(db, content_id)).to_dict()


@app.post("/v1/content/{content_id}/claims/candidates")
def claim_candidates(content_id: str, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    item = _content(db, content_id)
    candidates = extract_candidates(item)
    record_event(db, content_id=item.id, actor=p.name, action="claims.extract",
                 details={"content_hash": item.content_hash, "candidate_count": len(candidates)})
    db.commit()
    return {"content_id": item.id, "content_hash": item.content_hash, "candidates": candidates,
            "note": "Candidates are advisory and require human confirmation."}


@app.post("/v1/content/{content_id}/claims/confirm")
def confirm_claim(content_id: str, req: ClaimConfirmRequest, db: Session = Depends(get_db),
                  p: Principal = Depends(require_role("editor"))):
    item = _content(db, content_id, lock=True)
    candidate = next((c for c in extract_candidates(item) if c["candidate_id"] == req.candidate_id), None)
    if candidate is None:
        raise HTTPException(404, "claim candidate not found for current content version")
    claims = json.loads(item.claims_json or "[]")
    claim = {"text": candidate["text"], "claim_type": req.claim_type,
             "sources": [src.model_dump(mode="json") for src in req.sources], "confidence": req.confidence,
             "covers": []}
    if not any(c.get("text") == claim["text"] and c.get("claim_type") == claim["claim_type"] for c in claims):
        claims.append(claim)
    before = item.content_hash
    item.claims_json = json.dumps(claims)
    item.content_hash = governed_hash(item)
    item.state, item.updated_by = "draft", p.name
    db.add(item)
    record_event(db, content_id=item.id, actor=p.name, action="claims.confirm", decision="draft",
                 details={"candidate_id": req.candidate_id, "claim_type": req.claim_type,
                          "previous_hash": before, "content_hash": item.content_hash, "source_count": len(req.sources)})
    db.commit()
    return {"state": item.state, "content_hash": item.content_hash, "claim": claim}


@app.post("/v1/content/{content_id}/claims")
def add_claim(content_id: str, req: ClaimAddRequest, db: Session = Depends(get_db),
              p: Principal = Depends(require_role("editor"))):
    item = _content(db, content_id, lock=True)
    claims = json.loads(item.claims_json or "[]")
    claim = req.model_dump(mode="json")
    claim.setdefault("covers", [])
    claims.append(claim)
    before = item.content_hash
    item.claims_json = json.dumps(claims)
    item.content_hash = governed_hash(item)
    item.state, item.updated_by = "draft", p.name
    db.add(item)
    record_event(db, content_id=item.id, actor=p.name, action="claims.add", decision="draft",
                 details={"claim_type": req.claim_type, "previous_hash": before, "content_hash": item.content_hash,
                          "source_count": len(req.sources)})
    db.commit()
    return {"state": item.state, "content_hash": item.content_hash, "claim": claim}


@app.post("/v1/content/{content_id}/approve")
def approve(content_id: str, req: ApprovalRequest, db: Session = Depends(get_db),
            p: Principal = Depends(require_human("approver"))):
    item = _content(db, content_id, lock=True)
    if settings.four_eyes and item.classification in HIGH_RISK and p.name in {item.created_by, item.updated_by}:
        raise HTTPException(403, "four-eyes rule: the author or last editor of high-risk content cannot approve it")
    item.content_hash = governed_hash(item)  # never trust a stored hash (rows written by v1.0 used another scheme)
    item.approval_json = json.dumps({"approved_by": p.name, "identity": p.source, "attested_name": req.approver, "note": req.note,
                                     "approved_at": datetime.now(timezone.utc).isoformat(),
                                     "content_hash": item.content_hash,  # the approval is for this version only ...
                                     "dispositions_hash": dispositions_hash(item)})  # ... and for these reviewer decisions
    result = evaluate(item)
    if not result.passed:
        item.state = "blocked"
    elif item.state != "published":
        item.state = "approved"
    db.add(item)
    record_event(db, content_id=item.id, actor=p.name, action="content.approve", decision=item.state,
                 details={"attested_name": req.approver, "note": req.note, "content_hash": item.content_hash,
                          "blockers": result.blockers})
    db.commit()
    return {"state": item.state, "approved_by": p.name, "content_hash": item.content_hash, "gate": result.to_dict()}


@app.post("/v1/content/{content_id}/revoke")
def revoke(content_id: str, req: ApprovalRequest, db: Session = Depends(get_db),
           p: Principal = Depends(require_human("approver"))):
    """Withdraw approval. The item leaves rendered feeds immediately; already-pushed copies must be recalled at the destination."""
    item = _content(db, content_id, lock=True)
    item.approval_json = "{}"
    item.state = "blocked"
    db.add(item)
    record_event(db, content_id=item.id, actor=p.name, action="content.revoke", decision="blocked",
                 details={"note": req.note, "content_hash": item.content_hash})
    db.commit()
    return {"state": item.state}


@app.post("/v1/content/{content_id}/publish")
def publish(content_id: str, req: PublishRequest, db: Session = Depends(get_db),
            p: Principal = Depends(require_role("publisher"))):
    item, ep = _content(db, content_id, lock=True), _endpoint(db, req.endpoint_id)
    try:
        return push_content(db, item, ep, actor=p.name)
    except (GateBlocked, PolicyBlocked) as e:
        raise HTTPException(409, str(e))
    except ValueError as e:  # includes DestinationBlocked
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001 - delivery failure, already recorded
        raise HTTPException(502, (str(e).splitlines() or ["delivery failed"])[0][:300])


@app.get("/v1/content/{content_id}/deliveries", dependencies=[Depends(authenticate)])
def deliveries(content_id: str, db: Session = Depends(get_db)):
    _content(db, content_id)
    return [{"id": d.id, "endpoint_id": d.endpoint_id, "content_hash": d.content_hash, "status": d.status,
             "attempts": d.attempts, "response_code": d.response_code, "provider_id": d.provider_id, "error": d.error,
             "actor": d.actor, "created_at": d.created_at, "updated_at": d.updated_at}
            for d in db.query(Delivery).filter(Delivery.content_id == content_id).order_by(Delivery.created_at.desc()).all()]


# ----------------------------------------------------------------------------- schedules / feedback / inbox / AEO
@app.post("/v1/content/{content_id}/schedule", status_code=201)
def schedule_content(content_id: str, req: ScheduleCreate, db: Session = Depends(get_db),
                     p: Principal = Depends(require_role("publisher"))):
    item, ep = _content(db, content_id, lock=True), _endpoint(db, req.endpoint_id)
    try:
        row = schedule_delivery(db, item, ep, req.run_at, p.name)
    except (GateBlocked, PolicyBlocked) as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": row.id, "content_id": row.content_id, "endpoint_id": row.endpoint_id,
            "content_hash": row.content_hash, "run_at": row.run_at, "status": row.status}


@app.get("/v1/schedules", dependencies=[Depends(authenticate)])
def list_schedules(status: str | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    q = db.query(ScheduledDelivery)
    if status:
        q = q.filter(ScheduledDelivery.status == status)
    return [{"id": r.id, "content_id": r.content_id, "endpoint_id": r.endpoint_id, "content_hash": r.content_hash,
             "run_at": r.run_at, "status": r.status, "delivery_id": r.delivery_id, "error": r.error, "actor": r.actor}
            for r in q.order_by(ScheduledDelivery.run_at.asc()).limit(limit).all()]


@app.delete("/v1/schedules/{schedule_id}")
def cancel_schedule(schedule_id: str, db: Session = Depends(get_db), p: Principal = Depends(require_role("publisher"))):
    row = db.get(ScheduledDelivery, schedule_id)
    if not row:
        raise HTTPException(404, "schedule not found")
    if row.status != "scheduled":
        raise HTTPException(409, "only scheduled deliveries can be cancelled")
    row.status = "cancelled"
    db.add(row)
    record_event(db, content_id=row.content_id, actor=p.name, action="social.schedule.cancel", decision="cancelled",
                 details={"schedule_id": row.id, "endpoint_id": row.endpoint_id})
    db.commit()
    return {"id": row.id, "status": row.status}


@app.post("/v1/performance/events", status_code=201)
def add_performance_event(req: PerformanceEventCreate, db: Session = Depends(get_db),
                          p: Principal = Depends(require_role("editor"))):
    if req.content_id and not db.get(ContentItem, req.content_id):
        raise HTTPException(404, "content not found")
    if req.endpoint_id and not db.get(FeedEndpoint, req.endpoint_id):
        raise HTTPException(404, "feed endpoint not found")
    row = PerformanceEvent(id=req.id or str(uuid.uuid4()), content_id=req.content_id, endpoint_id=req.endpoint_id,
                           channel=req.channel, metric=req.metric, value=str(req.value), source=req.source,
                           period_start=req.period_start, period_end=req.period_end,
                           metadata_json=json.dumps(req.metadata))
    db.add(row)
    record_event(db, content_id=req.content_id, actor=p.name, action="performance.record", decision="accepted",
                 details={"metric": req.metric, "value": req.value, "channel": req.channel, "endpoint_id": req.endpoint_id})
    db.commit()
    return {"id": row.id, "metric": row.metric, "value": float(row.value), "channel": row.channel}


@app.get("/v1/performance", dependencies=[Depends(authenticate)])
def get_performance(content_id: str | None = None, days: int = Query(30, ge=1, le=3650), db: Session = Depends(get_db)):
    return performance_summary(db, content_id=content_id, days=days)


@app.get("/v1/performance/learn", dependencies=[Depends(authenticate)])
def get_performance_learning(content_id: str | None = None, days: int = Query(30, ge=1, le=3650), db: Session = Depends(get_db)):
    return performance_learn(db, content_id=content_id, days=days)


@app.post("/v1/engagement/inbox", status_code=201)
def add_inbox_message(req: InboxMessageCreate, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    if req.endpoint_id and not db.get(FeedEndpoint, req.endpoint_id):
        raise HTTPException(404, "feed endpoint not found")
    existing = db.query(InboxMessage).filter(InboxMessage.provider == req.provider, InboxMessage.external_id == req.external_id).first()
    if existing:
        return {"id": existing.id, "duplicate": True, "state": existing.state}
    row = InboxMessage(id=req.id or str(uuid.uuid4()), provider=req.provider, endpoint_id=req.endpoint_id,
                       thread_id=req.thread_id, external_id=req.external_id, sender=req.sender, body=req.body,
                       locale=req.locale, metadata_json=json.dumps(req.metadata),
                       received_at=req.received_at or datetime.now(timezone.utc))
    triage = triage_message(row)
    db.add(row)
    record_event(db, content_id=None, actor=f"Parinita Engagement Agent (ingest by {p.name})", action="engagement.inbox",
                 decision="triaged", details={"message_id": row.id, "provider": row.provider,
                                                "priority": row.priority, "intent": row.intent})
    db.commit()
    return {**triage, "duplicate": False, "provider": row.provider, "thread_id": row.thread_id}


@app.get("/v1/engagement/inbox", dependencies=[Depends(authenticate)])
def list_inbox(state: str | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    q = db.query(InboxMessage)
    if state:
        q = q.filter(InboxMessage.state == state)
    return [{"id": r.id, "provider": r.provider, "endpoint_id": r.endpoint_id, "thread_id": r.thread_id,
             "external_id": r.external_id, "sender": r.sender, "body": r.body, "locale": r.locale,
             "state": r.state, "priority": r.priority, "intent": r.intent, "response_draft": r.response_draft,
             "received_at": r.received_at}
            for r in q.order_by(InboxMessage.received_at.desc()).limit(limit).all()]


@app.patch("/v1/engagement/inbox/{message_id}")
def update_inbox_state(message_id: str, req: InboxStateUpdate, db: Session = Depends(get_db),
                       p: Principal = Depends(require_role("editor"))):
    row = db.get(InboxMessage, message_id)
    if not row:
        raise HTTPException(404, "message not found")
    row.state = req.state
    db.add(row)
    record_event(db, content_id=None, actor=p.name, action="engagement.state", decision=req.state,
                 details={"message_id": row.id, "provider": row.provider})
    db.commit()
    return {"id": row.id, "state": row.state}


# Public machine-readable AEO evidence surfaces: public classes only, and only while Gate still passes.
@app.get("/aeo/claims/{content_id}.json")
def public_aeo_claims(content_id: str, db: Session = Depends(get_db)):
    item = _content(db, content_id)
    if item.classification not in {"general", "pr", "social"}:
        raise HTTPException(404, "not found")
    try:
        return claim_manifest(item)
    except PermissionError:
        raise HTTPException(404, "not found")


@app.get("/aeo/content/{content_id}.jsonld")
def public_aeo_jsonld(content_id: str, db: Session = Depends(get_db)):
    item = _content(db, content_id)
    if item.classification not in {"general", "pr", "social"}:
        raise HTTPException(404, "not found")
    try:
        data = aeo_jsonld(item)
    except PermissionError:
        raise HTTPException(404, "not found")
    return JSONResponse(content=data, media_type="application/ld+json")


@app.post("/v1/aeo/queries", status_code=201)
def add_aeo_query(req: AEOQueryCreate, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    if req.id and db.get(AEOQuery, req.id):
        raise HTTPException(409, "AEO query id already exists")
    row = AEOQuery(id=req.id or str(uuid.uuid4()), name=req.name, prompt=req.prompt, brand=req.brand,
                   engines_json=json.dumps(req.engines), tags_json=json.dumps(req.tags), active=req.active)
    db.add(row)
    record_event(db, content_id=None, actor=p.name, action="aeo.query.create", details={"query_id": row.id, "brand": row.brand})
    db.commit()
    return {"id": row.id, "name": row.name, "brand": row.brand, "engines": req.engines, "active": row.active}


@app.get("/v1/aeo/queries", dependencies=[Depends(authenticate)])
def list_aeo_queries(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name, "prompt": r.prompt, "brand": r.brand,
             "engines": json.loads(r.engines_json or "[]"), "tags": json.loads(r.tags_json or "[]"), "active": r.active}
            for r in db.query(AEOQuery).order_by(AEOQuery.created_at.desc()).all()]


@app.post("/v1/aeo/probes", status_code=201)
def add_aeo_probe(req: AEOProbeCreate, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    query = db.get(AEOQuery, req.query_id) if req.query_id else None
    if req.query_id and not query:
        raise HTTPException(404, "AEO query not found")
    prompt = req.prompt or (query.prompt if query else "")
    brand = req.brand or (query.brand if query else "Parinita")
    mentioned = req.brand_mentioned if req.brand_mentioned is not None else (brand.lower() in req.response_text.lower() if req.response_text else False)
    row = AEOProbe(id=req.id or str(uuid.uuid4()), query_id=req.query_id, engine=req.engine, prompt=prompt,
                   brand=brand, response_text=req.response_text, citations_json=json.dumps(req.citations),
                   brand_mentioned=mentioned, source=req.source)
    db.add(row)
    record_event(db, content_id=None, actor=p.name, action="aeo.probe.record", decision="observed",
                 details={"probe_id": row.id, "query_id": req.query_id, "engine": req.engine,
                          "brand": brand, "brand_mentioned": mentioned, "citations": len(req.citations)})
    db.commit()
    return {"id": row.id, "engine": row.engine, "brand": row.brand, "brand_mentioned": row.brand_mentioned,
            "citations": req.citations}




@app.post("/v1/aeo/probes/run", status_code=201)
def run_aeo_probe(req: AEOProbeRun, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    query = db.get(AEOQuery, req.query_id) if req.query_id else None
    if req.query_id and not query:
        raise HTTPException(404, "AEO query not found")
    prompt = req.prompt or (query.prompt if query else "")
    brand = req.brand or (query.brand if query else "Parinita")
    if not prompt:
        raise HTTPException(422, "prompt is required")
    try:
        observed = run_rest_probe(url=req.url, prompt=prompt, brand=brand, request_body=req.request_body,
                                  prompt_field=req.prompt_field, answer_path=req.answer_path,
                                  citations_path=req.citations_path, headers=req.headers,
                                  bearer_token_env=req.bearer_token_env)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # provider/network failure; do not leak internals
        raise HTTPException(502, f"answer-engine probe failed: {type(exc).__name__}")
    row = AEOProbe(id=str(uuid.uuid4()), query_id=req.query_id, engine=req.engine, prompt=prompt, brand=brand,
                   response_text=observed["response_text"], citations_json=json.dumps(observed["citations"]),
                   brand_mentioned=observed["brand_mentioned"], source="rest-probe")
    db.add(row)
    record_event(db, content_id=None, actor=f"Parinita AEO Agent (run by {p.name})", action="aeo.probe.run", decision="observed",
                 details={"probe_id": row.id, "query_id": req.query_id, "engine": req.engine,
                          "brand_mentioned": row.brand_mentioned, "citations": len(observed["citations"])})
    db.commit()
    return {"id": row.id, "engine": row.engine, "brand": row.brand, "brand_mentioned": row.brand_mentioned,
            "citations": observed["citations"], "status_code": observed["status_code"]}

@app.get("/v1/aeo/visibility", dependencies=[Depends(authenticate)])
def aeo_visibility_route(brand: str = "Parinita", days: int = Query(30, ge=1, le=3650), db: Session = Depends(get_db)):
    return aeo_visibility(db, brand, days)


@app.get("/v1/aeo/recommendations", dependencies=[Depends(authenticate)])
def aeo_recommendations_route(brand: str = "Parinita", days: int = Query(30, ge=1, le=3650), db: Session = Depends(get_db)):
    return aeo_recommendations(db, brand, days)


# ----------------------------------------------------------------------------- feeds
@app.post("/v1/feeds", status_code=201)
def add_feed(payload: FeedEndpointCreate, db: Session = Depends(get_db), p: Principal = Depends(require_role("admin"))):
    if db.query(FeedEndpoint).filter(FeedEndpoint.slug == payload.slug).first():
        raise HTTPException(409, "slug already exists")
    if payload.id and db.get(FeedEndpoint, payload.id):
        raise HTTPException(409, "feed endpoint id already exists")
    try:
        validate_endpoint_config(payload.url, payload.config, needs_url=_needs_url(payload.protocol, payload.direction, payload.config),
                                 protocol=payload.protocol, direction=payload.direction)
    except DestinationBlocked as e:
        raise HTTPException(422, str(e))
    ep = FeedEndpoint(id=payload.id or str(uuid.uuid4()), name=payload.name, slug=payload.slug, direction=payload.direction,
                      protocol=payload.protocol, url=payload.url, channel=payload.channel,
                      config_json=json.dumps(payload.config), enabled=payload.enabled, poll_seconds=payload.poll_seconds)
    db.add(ep)
    record_event(db, content_id=None, actor=p.name, action="feed.create",
                 details={"endpoint_id": ep.id, "slug": ep.slug, "protocol": ep.protocol, "direction": ep.direction, "url": ep.url})
    db.commit()
    return _endpoint_view(ep)


@app.get("/v1/feeds", dependencies=[Depends(authenticate)])
def list_feeds(db: Session = Depends(get_db)):
    return [_endpoint_view(e) for e in db.query(FeedEndpoint).order_by(FeedEndpoint.created_at.asc()).all()]


@app.patch("/v1/feeds/{endpoint_id}")
def edit_feed(endpoint_id: str, patch: FeedEndpointUpdate, db: Session = Depends(get_db),
              p: Principal = Depends(require_role("admin"))):
    ep = _endpoint(db, endpoint_id)
    data = patch.model_dump(exclude_unset=True)
    try:
        cfg = data["config"] if data.get("config") is not None else json.loads(ep.config_json or "{}")
        url = data["url"] if data.get("url") is not None else ep.url
        validate_endpoint_config(url, cfg, needs_url=_needs_url(ep.protocol, ep.direction, cfg),
                                 protocol=ep.protocol, direction=ep.direction)
    except DestinationBlocked as e:
        raise HTTPException(422, str(e))
    for f in ("name", "url", "channel", "enabled", "poll_seconds"):
        if data.get(f) is not None:
            setattr(ep, f, data[f])
    if data.get("config") is not None:
        ep.config_json = json.dumps(data["config"])
    db.add(ep)
    record_event(db, content_id=None, actor=p.name, action="feed.update",
                 details={"endpoint_id": ep.id, "fields": sorted(k for k, v in data.items() if v is not None), "enabled": ep.enabled})
    db.commit()
    return _endpoint_view(ep)


@app.post("/v1/feeds/{endpoint_id}/sync")
def sync_feed(endpoint_id: str, db: Session = Depends(get_db), p: Principal = Depends(require_role("admin"))):
    ep = _endpoint(db, endpoint_id)
    try:
        return ingest_endpoint(db, ep, actor=p.name)
    except ValueError as e:  # bad endpoint, blocked destination, oversized or malformed feed
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        # First line only: never echo SQL or stack detail to the caller. Full error is on the endpoint record.
        raise HTTPException(502, f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:300]}")


# ----------------------------------------------------------------------------- campaigns
@app.post("/v1/campaigns", status_code=201)
def add_campaign(payload: CampaignCreate, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    if payload.id and db.get(Campaign, payload.id):
        raise HTTPException(409, "campaign id already exists")
    c = Campaign(id=payload.id or str(uuid.uuid4()), name=payload.name, objective=payload.objective,
                 audiences_json=json.dumps(payload.audiences), channels_json=json.dumps(payload.channels),
                 default_cta_url=payload.default_cta_url)
    db.add(c)
    record_event(db, content_id=None, actor=p.name, action="campaign.create", details={"campaign_id": c.id, "name": c.name})
    db.commit()
    return {"id": c.id, "name": c.name, "status": c.status}


@app.get("/v1/campaigns", dependencies=[Depends(authenticate)])
def list_campaigns(db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name, "objective": c.objective, "audiences": json.loads(c.audiences_json or "[]"),
             "channels": json.loads(c.channels_json or "[]"), "default_cta_url": c.default_cta_url, "status": c.status}
            for c in db.query(Campaign).order_by(Campaign.created_at.desc()).all()]


# ----------------------------------------------------------------------------- audit
@app.get("/v1/audit", dependencies=[Depends(require_role("auditor"))])
def audit(limit: int = Query(100, ge=1, le=500), content_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(AuditEvent)
    if content_id:
        q = q.filter(AuditEvent.content_id == content_id)
    return [{"seq": e.seq, "event_id": e.event_id, "ts": e.ts, "content_id": e.content_id, "actor": e.actor, "action": e.action,
             "decision": e.decision, "details": json.loads(e.details_json or "{}"), "hash": e.event_hash, "prev_hash": e.prev_hash}
            for e in q.order_by(AuditEvent.seq.desc()).limit(limit).all()]


@app.get("/v1/audit/verify", dependencies=[Depends(require_role("auditor"))])
def audit_verify(db: Session = Depends(get_db)):
    """Recomputes the whole chain. Anchor head_hash outside this database to detect wholesale rewrites."""
    return verify_chain(db)


# ----------------------------------------------------------------------------- v1.6 media intelligence / opportunity / claim graph / Chrysalis
@app.post("/v1/media/contacts", status_code=201)
def add_media_contact(req: MediaContactCreate, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    row, created = upsert_contact(db, req.model_dump(), p.name)
    db.commit()
    return {"id": row.id, "created": created, "provider": row.provider, "external_id": row.external_id,
            "name": row.name, "outlet": row.outlet, "beat": row.beat, "profile_url": row.profile_url,
            "influence_score": float(row.influence_score or 0)}


@app.get("/v1/media/contacts", dependencies=[Depends(authenticate)])
def list_media_contacts(provider: str | None = None, outlet: str | None = None,
                        limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
                        p: Principal = Depends(authenticate)):
    q = db.query(MediaContact)
    if provider:
        q = q.filter(MediaContact.provider == provider)
    if outlet:
        q = q.filter(MediaContact.outlet == outlet)
    return [{"id": r.id, "provider": r.provider, "external_id": r.external_id, "name": r.name,
             "outlet": r.outlet, "beat": r.beat, "email": r.email if p.has("editor") else "", "profile_url": r.profile_url,
             "location": r.location, "influence_score": float(r.influence_score or 0)}
            for r in q.order_by(MediaContact.updated_at.desc()).limit(limit).all()]


@app.post("/v1/media/coverage", status_code=201)
def add_media_coverage(req: MediaCoverageCreate, db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    data = req.model_dump()
    if req.content_id and not db.get(ContentItem, req.content_id):
        raise HTTPException(404, "content not found")
    row, created = upsert_coverage(db, data, p.name)
    observations = []
    if row.content_id:
        item = db.get(ContentItem, row.content_id)
        observations = observe_coverage(db, item, row)
    db.commit()
    return {"id": row.id, "created": created, "provider": row.provider, "external_id": row.external_id,
            "title": row.title, "url": row.url, "outlet": row.outlet, "author": row.author,
            "content_id": row.content_id, "claim_observations": len(observations)}


@app.get("/v1/media/coverage", dependencies=[Depends(authenticate)])
def list_media_coverage(content_id: str | None = None, days: int = Query(30, ge=1, le=3650),
                        limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    q = db.query(MediaCoverage)
    if content_id:
        q = q.filter(MediaCoverage.content_id == content_id)
    rows = q.order_by(MediaCoverage.published_at.desc(), MediaCoverage.created_at.desc()).limit(limit).all()
    return {"summary": coverage_summary(db, days),
            "items": [{"id": r.id, "provider": r.provider, "external_id": r.external_id, "title": r.title,
                       "url": r.url, "outlet": r.outlet, "author": r.author, "sentiment": r.sentiment,
                       "content_id": r.content_id, "published_at": r.published_at,
                       "topics": json.loads(r.topics_json or "[]")} for r in rows]}


@app.get("/v1/content/{content_id}/media-targets", dependencies=[Depends(authenticate)])
def media_targets(content_id: str, limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return {"content_id": content_id, "targets": rank_targets(db, _content(db, content_id), limit)}


@app.post("/v1/opportunities/refresh")
def opportunities_refresh(brand: str = "Parinita", days: int = Query(30, ge=1, le=365),
                          db: Session = Depends(get_db), p: Principal = Depends(require_role("editor"))):
    return refresh_opportunities(db, brand=brand, days=days, actor=p.name)


@app.get("/v1/opportunities", dependencies=[Depends(authenticate)])
def opportunities_list(status: str | None = "new", kind: str | None = None,
                       limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    q = db.query(Opportunity)
    if status:
        q = q.filter(Opportunity.status == status)
    if kind:
        q = q.filter(Opportunity.kind == kind)
    rows = q.all()
    rows.sort(key=lambda r: (-float(r.score or 0), r.created_at))
    return [opportunity_view(r) for r in rows[:limit]]


@app.patch("/v1/opportunities/{opportunity_id}")
def opportunity_state(opportunity_id: str, req: OpportunityStateUpdate, db: Session = Depends(get_db),
                      p: Principal = Depends(require_role("editor"))):
    row = db.get(Opportunity, opportunity_id)
    if not row:
        raise HTTPException(404, "opportunity not found")
    row.status = req.status; row.updated_at = datetime.now(timezone.utc); db.add(row)
    record_event(db, content_id=None, actor=p.name, action="opportunity.state", decision=req.status,
                 details={"opportunity_id": row.id, "kind": row.kind, "title": row.title})
    db.commit()
    return opportunity_view(row)


@app.post("/v1/content/{content_id}/claim-observations", status_code=201)
def add_claim_observation(content_id: str, req: ClaimObservationCreate, db: Session = Depends(get_db),
                          p: Principal = Depends(require_role("editor"))):
    item = _content(db, content_id)
    row = ClaimObservation(id=req.id or str(uuid.uuid4()), content_id=item.id, sentence_hash=req.sentence_hash,
                           claim_text=req.claim_text, observation_type=req.observation_type, provider=req.provider,
                           uri=req.uri, observed_text=req.observed_text, matched_score=str(req.matched_score),
                           metadata_json=json.dumps(req.metadata))
    db.add(row)
    record_event(db, content_id=item.id, actor=p.name, action="claim.observation", decision="recorded",
                 details={"observation_id": row.id, "type": row.observation_type, "provider": row.provider,
                          "uri": row.uri, "matched_score": req.matched_score})
    db.commit()
    return {"id": row.id, "content_id": item.id, "observation_type": row.observation_type, "uri": row.uri}


@app.get("/v1/content/{content_id}/claim-graph", dependencies=[Depends(authenticate)])
def content_claim_graph(content_id: str, db: Session = Depends(get_db)):
    return claim_graph(db, _content(db, content_id))


@app.get("/v1/chrysalis/status", dependencies=[Depends(authenticate)])
def chrysalis_status(db: Session = Depends(get_db)):
    latest = db.query(ChrysalisAnchor).order_by(ChrysalisAnchor.created_at.desc()).first()
    return {"enabled": settings.chrysalis_enabled, "anchor_url_configured": bool(settings.chrysalis_anchor_url),
            "fail_closed_high_risk": settings.chrysalis_fail_closed_high_risk,
            "fail_closed_all": settings.chrysalis_fail_closed_all,
            "latest": chrysalis_view(latest) if latest else None,
            "architecture": "GrowthOS local audit chain -> Chrysalis external assurance anchor"}


@app.post("/v1/chrysalis/anchor/audit")
def chrysalis_anchor_audit(db: Session = Depends(get_db), p: Principal = Depends(require_role("auditor"))):
    if not settings.chrysalis_enabled:
        raise HTTPException(409, "Chrysalis anchoring is not enabled")
    try:
        row = anchor_audit_head(db, actor=p.name)
    except Exception as exc:
        raise HTTPException(502, f"Chrysalis audit anchor failed: {type(exc).__name__}")
    return chrysalis_view(row)


@app.post("/v1/content/{content_id}/chrysalis/attest")
def chrysalis_attest_release(content_id: str, db: Session = Depends(get_db),
                             p: Principal = Depends(require_role("auditor"))):
    if not settings.chrysalis_enabled:
        raise HTTPException(409, "Chrysalis anchoring is not enabled")
    item = _content(db, content_id)
    try:
        row = anchor_release(db, item, actor=p.name)
    except RuntimeError as exc:  # GrowthOS's own refusal messages (gate / chain verification)
        raise HTTPException(409, str(exc))
    except Exception as exc:  # noqa: BLE001 - transport/provider detail stays on the anchor row and audit chain
        raise HTTPException(502, f"Chrysalis release attestation failed: {type(exc).__name__}")
    return chrysalis_view(row)


@app.post("/v1/content/{content_id}/video")
def create_short_video(content_id: str, db: Session = Depends(get_db),
                       p: Principal = Depends(require_role("editor"))):
    from .short_video import render_short_video
    item = _content(db, content_id)
    try:
        video = render_short_video(serialize(item))
    except ValueError as exc:
        raise HTTPException(503, str(exc))
    return Response(video, media_type="video/mp4", headers={
        "Content-Disposition": 'attachment; filename="growthos-15s.mp4"',
        "Cache-Control": "no-store"})
