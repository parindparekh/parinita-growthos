"""Answer Engine Optimization (AEO/GEO) instrumentation.

GrowthOS does not claim a universal answer-engine publishing protocol exists. Instead it:
1) exposes governed, sourced claims and structured metadata from approved releases;
2) records observed answer-engine responses/citations from live adapters or operators;
3) computes transparent visibility/citation metrics and grounded recommendations.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from .gate import evaluate
from .models import AEOProbe, ContentItem


def _claims(item: ContentItem) -> list[dict]:
    try:
        rows = json.loads(item.claims_json or "[]")
    except ValueError:
        return []
    return rows if isinstance(rows, list) else []


def claim_manifest(item: ContentItem) -> dict:
    """Machine-readable evidence pack for one governed release.

    Only claims with at least one source are emitted. The manifest says what GrowthOS has
    recorded and approved; it does not certify the external source itself is truthful.
    """
    gate = evaluate(item)
    if item.state not in {"approved", "published"} or not gate.passed:
        raise PermissionError("content is not currently cleared for public evidence export")
    claims = []
    for c in _claims(item):
        sources = [s for s in (c.get("sources") or []) if isinstance(s, dict) and s.get("uri")]
        if not sources:
            continue
        claims.append({
            "text": c.get("text", ""),
            "type": c.get("claim_type", "fact"),
            "sources": sources,
            "covers": c.get("covers") or [],
            "confidence": c.get("confidence"),
        })
    return {
        "schema": "parinita.growthos.claim-manifest.v1",
        "content_id": item.id,
        "content_hash": item.content_hash,
        "title": item.title,
        "canonical_url": item.source if str(item.source).startswith(("http://", "https://")) else "",
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "claims": claims,
        "note": "Source presence and approval are provenance controls, not independent proof that an external source is correct.",
    }


def jsonld(item: ContentItem) -> dict:
    """Conservative Schema.org JSON-LD generated only from governed fields."""
    manifest = claim_manifest(item)
    kind = "PodcastEpisode" if item.content_type in {"podcast", "podcast_episode"} else "NewsArticle"
    data = {
        "@context": "https://schema.org",
        "@type": kind,
        "headline": item.title,
        "description": item.summary or item.body[:500],
        "inLanguage": item.locale,
        "identifier": item.id,
        "datePublished": manifest["published_at"],
        "citation": sorted({s["uri"] for c in manifest["claims"] for s in c["sources"] if s.get("uri")}),
    }
    if manifest["canonical_url"]:
        data["url"] = manifest["canonical_url"]
    return data


def _domain(uri: str) -> str:
    try:
        return urlparse(uri).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def visibility_summary(db: Session, brand: str = "Parinita", days: int = 30) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))
    probes = db.query(AEOProbe).filter(AEOProbe.brand == brand, AEOProbe.created_at >= cutoff).all()
    mentions = sum(1 for p in probes if p.brand_mentioned)
    domains: Counter[str] = Counter()
    by_engine: dict[str, dict[str, int]] = {}
    for p in probes:
        row = by_engine.setdefault(p.engine, {"probes": 0, "mentions": 0})
        row["probes"] += 1
        row["mentions"] += int(bool(p.brand_mentioned))
        try:
            citations = json.loads(p.citations_json or "[]")
        except ValueError:
            citations = []
        for u in citations if isinstance(citations, list) else []:
            d = _domain(str(u))
            if d:
                domains[d] += 1
    for row in by_engine.values():
        row["visibility_rate"] = round(row["mentions"] / row["probes"], 4) if row["probes"] else 0
    return {
        "brand": brand,
        "days": days,
        "probes": len(probes),
        "mentions": mentions,
        "visibility_rate": round(mentions / len(probes), 4) if probes else 0,
        "by_engine": by_engine,
        "top_citation_domains": [{"domain": d, "citations": n} for d, n in domains.most_common(20)],
    }


def recommendations(db: Session, brand: str = "Parinita", days: int = 30) -> dict:
    summary = visibility_summary(db, brand, days)
    actions = []
    if summary["probes"] == 0:
        actions.append({"priority": "high", "action": "add-probes", "why": "No answer-engine observations exist for this window."})
    elif summary["visibility_rate"] < 0.5:
        actions.append({"priority": "high", "action": "review-missing-prompts", "why": "Brand appears in fewer than half of observed answers."})
    if summary["top_citation_domains"]:
        actions.append({"priority": "normal", "action": "review-citation-sources", "why": "Use the cited domains to prioritize earned-media and source-quality work."})
    actions.append({"priority": "normal", "action": "publish-governed-claim-manifests", "why": "Keep approved claims, citations and canonical metadata machine-readable alongside releases."})
    return {"summary": summary, "actions": actions,
            "note": "Recommendations are descriptive heuristics from recorded observations; they do not guarantee answer-engine ranking or citation."}


def _dot(obj, path: str):
    cur = obj
    for part in [p for p in (path or "").split(".") if p]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def run_rest_probe(*, url: str, prompt: str, brand: str, request_body: dict, prompt_field: str,
                   answer_path: str, citations_path: str, headers: dict[str, str], bearer_token_env: str = "") -> dict:
    """Run a configurable REST answer-engine probe through the same SSRF/secret boundary as Feed Fabric.

    This avoids pretending every answer engine has the same API. Operators map the request field and response
    paths for the provider they are licensed to query.
    """
    import copy
    from .netguard import clean_headers, safe_post, secret_from_env
    body = copy.deepcopy(request_body or {})
    body[prompt_field or "prompt"] = prompt
    h = {"Content-Type": "application/json", **clean_headers(headers or {})}
    if bearer_token_env:
        from .config import settings
        prefix = settings.aeo_probe_secret_prefix
        if not str(bearer_token_env).startswith(prefix):
            # A probe URL is editor-supplied. Limiting the secrets it may carry to the AEO namespace means a probe
            # pointed at an arbitrary public host can never exfiltrate provider, messaging or Chrysalis tokens.
            raise ValueError(f"answer-engine probes may only reference secrets named {prefix}*")
        token = secret_from_env(bearer_token_env)
        if not token:
            raise ValueError(f"secret {bearer_token_env} is not set")
        h["Authorization"] = "Bearer " + token
    r = safe_post(url, content=json.dumps(body).encode(), headers=h)
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError as exc:
        raise ValueError("answer-engine endpoint did not return JSON") from exc
    answer = _dot(data, answer_path)
    citations = _dot(data, citations_path)
    answer_text = str(answer or "")
    if isinstance(citations, list):
        urls = []
        for c in citations:
            if isinstance(c, str):
                urls.append(c)
            elif isinstance(c, dict):
                u = c.get("url") or c.get("uri") or c.get("link")
                if u:
                    urls.append(str(u))
    else:
        urls = []
    return {"response_text": answer_text, "citations": urls[:100],
            "brand_mentioned": bool(brand and brand.lower() in answer_text.lower()), "status_code": r.status_code}
