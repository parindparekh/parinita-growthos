"""GrowthOS Claim Graph.

This is a communications/provenance graph. It intentionally does NOT use the name Lineage;
Parinita Chrysalis Lineage remains the causal-forensics component across trust domains.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict

from sqlalchemy.orm import Session

from .gate import account
from .models import AEOProbe, ClaimObservation, ContentItem, Delivery, FeedEndpoint, MediaCoverage, PerformanceEvent


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", (text or "").lower()) if w not in {"the","and","for","with","from","that","this","are","was","were"}}


def _sim(a: str, b: str) -> float:
    x, y = _terms(a), _terms(b)
    return round(len(x & y) / max(1, len(x)), 4) if x else 0.0


def observe_coverage(db: Session, item: ContentItem, coverage: MediaCoverage, threshold: float = 0.45) -> list[ClaimObservation]:
    claims = json.loads(item.claims_json or "[]")
    created = []
    hay = " ".join([coverage.title, coverage.body])
    sentences = {r["hash"]: r["text"] for r in account(item)}
    for claim in claims:
        score = _sim(str(claim.get("text") or ""), hay)
        if score < threshold:
            continue
        covers = claim.get("covers") or [""]
        for h in covers[:10]:
            existing = db.query(ClaimObservation).filter(ClaimObservation.content_id == item.id,
                                                          ClaimObservation.sentence_hash == str(h),
                                                          ClaimObservation.observation_type == "earned-media",
                                                          ClaimObservation.uri == coverage.url).first()
            if existing:
                created.append(existing); continue
            row = ClaimObservation(id=str(uuid.uuid4()), content_id=item.id, sentence_hash=str(h),
                                   claim_text=str(claim.get("text") or sentences.get(str(h), "")),
                                   observation_type="earned-media", provider=coverage.provider, uri=coverage.url,
                                   observed_text=(coverage.title + "\n" + coverage.body[:1200]).strip(), matched_score=str(score),
                                   metadata_json=json.dumps({"coverage_id": coverage.id, "outlet": coverage.outlet, "author": coverage.author}))
            db.add(row); created.append(row)
    return created


def graph(db: Session, item: ContentItem) -> dict:
    nodes, edges = [], []
    nodes.append({"id": f"release:{item.id}:{item.content_hash}", "type": "release", "label": item.title,
                  "data": {"content_id": item.id, "content_hash": item.content_hash, "state": item.state}})
    release_id = nodes[0]["id"]
    claims = json.loads(item.claims_json or "[]")
    for idx, c in enumerate(claims):
        cid = f"claim:{item.id}:{idx}"
        nodes.append({"id": cid, "type": "claim", "label": c.get("text", "")[:240], "data": {"claim_type": c.get("claim_type"), "covers": c.get("covers") or []}})
        edges.append({"from": cid, "to": release_id, "type": "approved-in"})
        for sidx, s in enumerate(c.get("sources") or []):
            sid = f"source:{item.id}:{idx}:{sidx}"
            nodes.append({"id": sid, "type": "source", "label": s.get("title") or s.get("uri"), "data": s})
            edges.append({"from": sid, "to": cid, "type": "supports"})

    eps = {e.id: e for e in db.query(FeedEndpoint).all()}
    for d in db.query(Delivery).filter(Delivery.content_id == item.id, Delivery.content_hash == item.content_hash).all():
        did = f"delivery:{d.id}"
        ep = eps.get(d.endpoint_id)
        nodes.append({"id": did, "type": "delivery", "label": (ep.name if ep else d.endpoint_id),
                      "data": {"status": d.status, "channel": ep.channel if ep else "", "provider_id": d.provider_id}})
        edges.append({"from": release_id, "to": did, "type": "distributed-as"})

    for o in db.query(ClaimObservation).filter(ClaimObservation.content_id == item.id).all():
        oid = f"observation:{o.id}"
        nodes.append({"id": oid, "type": o.observation_type, "label": o.uri or o.provider,
                      "data": {"provider": o.provider, "uri": o.uri, "matched_score": float(o.matched_score or 0), "observed_text": o.observed_text[:500]}})
        target = next((n["id"] for n in nodes if n["type"] == "claim" and o.claim_text and o.claim_text[:80] in n["label"]), release_id)
        edges.append({"from": target, "to": oid, "type": "observed-in"})

    # Exact citation/source matching adds AEO edges without claiming semantic attribution.
    source_uris = {n["data"].get("uri"): n["id"] for n in nodes if n["type"] == "source" and n["data"].get("uri")}
    for p in db.query(AEOProbe).all():
        try: citations = json.loads(p.citations_json or "[]")
        except ValueError: citations = []
        for uri in citations if isinstance(citations, list) else []:
            if uri in source_uris:
                aid = f"aeo:{p.id}:{hashlib.sha256(uri.encode("utf-8")).hexdigest()[:16]}"
                nodes.append({"id": aid, "type": "aeo-citation", "label": p.engine, "data": {"engine": p.engine, "uri": uri, "brand_mentioned": p.brand_mentioned}})
                edges.append({"from": source_uris[uri], "to": aid, "type": "cited-by"})

    perf = defaultdict(float)
    for e in db.query(PerformanceEvent).filter(PerformanceEvent.content_id == item.id).all():
        try: perf[e.metric] += float(e.value)
        except ValueError: pass
    if perf:
        pid = f"performance:{item.id}"
        nodes.append({"id": pid, "type": "performance", "label": "Observed outcomes", "data": dict(perf)})
        edges.append({"from": release_id, "to": pid, "type": "measured-by"})
    return {"schema": "parinita.growthos.claim-graph.v1", "content_id": item.id, "content_hash": item.content_hash,
            "nodes": nodes, "edges": edges,
            "note": "This graph records provenance and observed relationships. It does not independently prove source truth or causal influence."}
