"""Sentence-level claim candidate extraction.

Candidates are advisory and never become evidence automatically. A human editor must
confirm a candidate with a claim type and sources before it enters the governed claim
ledger. This closes the v1.1 workflow gap without pretending a lexical extractor can
judge truth.
"""
import hashlib
import json
import re

from .gate import numeric_tokens, quotations, superlatives
from .models import ContentItem

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_FORECAST = re.compile(r"\b(?:forecast|projected?|projection|target|expect(?:s|ed|ing)?|anticipate|aims?\s+to|plans?\s+to|intends?\s+to|guidance|outlook|goal)\b", re.I)
_ASSERTIVE = re.compile(r"\b(?:is|are|was|were|has|have|had|operates?|provides?|supports?|serves?|signed|launched|grew|increased|decreased|reduced|delivers?|includes?|contains?|uses?|built|deploys?|offers?)\b", re.I)
_OPINION = re.compile(r"\b(?:believe|think|feel|hope|opinion|perhaps|maybe|could|might|should)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def extract_candidates(item: ContentItem) -> list[dict]:
    text = "\n".join([item.title or "", item.summary or "", item.body or ""])
    claims = json.loads(item.claims_json or "[]")
    existing = [_norm(c.get("text", "")) for c in claims]
    seen: set[str] = set()
    out: list[dict] = []
    for raw in _SENTENCE.split(text):
        sentence = re.sub(r"\s+", " ", raw).strip()
        if len(sentence) < 12 or sentence.endswith("?"):
            continue
        n = numeric_tokens(sentence)
        q = quotations(sentence)
        s = superlatives(sentence)
        forecast = bool(_FORECAST.search(sentence))
        assertive = bool(_ASSERTIVE.search(sentence)) and not bool(_OPINION.search(sentence))
        reasons = []
        if n:
            reasons.append("numeric")
        if q:
            reasons.append("quotation")
        if s:
            reasons.append("superlative")
        if forecast:
            reasons.append("forecast-language")
        if assertive and not reasons:
            reasons.append("assertive-prose")
        if not reasons:
            continue
        normalized = _norm(sentence)
        if normalized in seen or any(normalized in c or c in normalized for c in existing if c):
            continue
        seen.add(normalized)
        ctype = "quote" if q else ("forecast" if forecast else "fact")
        cid = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        out.append({"candidate_id": cid, "text": sentence[:2000], "suggested_type": ctype,
                    "reasons": reasons, "numeric_tokens": sorted(n), "superlatives": sorted(s)})
    return out[:200]
