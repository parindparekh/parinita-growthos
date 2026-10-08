"""Parinita Hallucination Gate - deterministic release policy (policy version 1.2).

What it enforces:
  1. Declared fact/quote claims need at least one well-formed source reference.
  2. Forecast claims must carry explicit projection language.
  3. COVERAGE: numeric assertions, direct quotations and superlatives found in the
     title/summary/body must appear in a *supported* claim. Declaring one unrelated
     claim no longer switches the scan off.
  4. High-risk classes need a human approval that is bound to the exact content hash.
     Editing anything governed invalidates the approval.
  5. SENTENCE ACCOUNTING (new in 1.2): every assertive sentence in title/summary/body must be
     either covered by a supported claim (explicit link or lexical match) or dispositioned by a
     reviewer as needing no evidence. Prose with no number, quote or superlative is no longer invisible.

What it does not do: decide whether a cited source is true. It verifies evidence
coverage and policy, not facts.
"""
import hashlib
import json
import re
from dataclasses import asdict, dataclass

from .config import settings
from .content import governed_hash
from .models import ContentItem
from .schemas import valid_source_uri

POLICY_VERSION = "1.2"
HIGH_RISK = frozenset({"investor", "regulated", "legal", "health", "financial"})

_FORECAST_LABEL = re.compile(
    r"\b(?:forecast(?:s|ed|ing)?|estimate[sd]?|estimated|projection(?:s)?|projected|projects?\s+(?:to|that)|"
    r"target(?:s|ed|ing)?|expect(?:s|ed|ing|ation|ations)?|anticipate[sd]?|plans?\s+to|aims?\s+to|"
    r"intends?\s+to|guidance|outlook|goal\s+(?:is|of))\b", re.I)

_URL = re.compile(r"https?://\S+", re.I)
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
          r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_DATE_NUM = re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b", re.I)
_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_VERSION = re.compile(r"\bv\d+(?:\.\d+)*\b|\b\d+\.\d+\.\d+(?:\.\d+)*\b", re.I)
_NUMBER = re.compile(
    r"(?P<cur>[$€£₹¥]\s?)?(?<![\w.])(?<![A-Za-z]-)(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"(?P<unit>%|\s?percent\b|\s?pct\b|\s?bps\b|\s?basis\s+points\b|x\b|[KkMmBb]\b|bn\b|"
    r"\s?thousand\b|\s?million\b|\s?billion\b|\s?trillion\b)?", re.I)
_UNIT_NORM = {"percent": "%", "pct": "%", "basispoints": "bps", "thousand": "k", "million": "m",
              "billion": "b", "bn": "b", "trillion": "t"}
_SUPERLATIVE = re.compile(
    r"(?:#\s?1\b|\bnumber\s+one\b|\bno\.\s?1\b|\b(?:largest|biggest|fastest|cheapest|world'?s\s+first|first[- ]ever|"
    r"industry[- ]leading|market[- ]leading|best[- ]in[- ]class|unmatched|unrivall?ed|guarantee[sd]?)\b)", re.I)
_QUOTE = re.compile(r"[\"\u201c]([^\"\u201c\u201d]{25,}?)[\"\u201d]")


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def numeric_tokens(text_: str) -> set[str]:
    """Normalised numeric assertions: currency, percentages, magnitudes, multipliers, counts >= 10.
    Dates, clock times, version numbers, URLs, bare years and identifier suffixes
    (SHA-256, ML-DSA-87) are ignored. Heuristic by design: it over-flags rather than under-flags."""
    t = _URL.sub(" ", text_ or "")
    for rx in (_DATE_NUM, _TIME, _VERSION):
        t = rx.sub(" ", t)
    out: set[str] = set()
    for m in _NUMBER.finditer(t):
        raw = m.group("num").rstrip(",").replace(",", "")
        cur, unit = bool(m.group("cur")), re.sub(r"\s+", "", (m.group("unit") or "").lower())
        unit = _UNIT_NORM.get(unit, unit)
        if not cur and not unit:
            try:
                val = float(raw)
            except ValueError:
                continue
            if val < 10:
                continue
            if "." not in raw and len(raw) == 4 and 1900 <= val <= 2099:
                continue  # a year
        if "." in raw:
            raw = raw.rstrip("0").rstrip(".")
        out.add(raw + unit)
    return out


def superlatives(text_: str) -> set[str]:
    return {_norm_ws(m.group(0)).replace("# 1", "#1") for m in _SUPERLATIVE.finditer(text_ or "")}


def quotations(text_: str) -> set[str]:
    return {_norm_ws(m.group(1)) for m in _QUOTE.finditer(text_ or "")}


# ----------------------------------------------------------------------------- sentence accounting
_ABBR = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "inc", "ltd", "co", "corp", "llc", "plc", "vs", "etc", "eg", "ie",
         "us", "uk", "no", "fig", "approx", "dept", "est", "gen", "gov", "rep", "sen", "jan", "feb", "mar", "apr", "jun",
         "jul", "aug", "sep", "sept", "oct", "nov", "dec", "am", "pm"}
_BOUNDARY = re.compile(r"([.!?]+[\"'\u201d\u2019)\]]*)\s+(?=[\"'\u201c\u2018(\[]?[A-Z0-9])")
_WORD = re.compile(r"[a-z0-9]+(?:['\u2019.-][a-z0-9]+)*")
_STOP = frozenset("""a an the and or but nor so yet of to in on at by for with from as into onto over under about after before
between through during without within against across per via is are was were be been being am do does did have has had having
will would shall should can could may might must it its this that these those there here we our us you your they their them he
she his her i my me not no also very more most than then when while where which who whom whose what how if because just only
too now new all any each both such same other some own up out off""".split())
_CTA = frozenset("""learn read see visit join register contact download try follow subscribe find click watch listen rsvp
explore discover request schedule apply get""".split())
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_BULLET = re.compile(r"^\s*(?:[-*\u2022\u2013\u2014]|\d{1,2}[.)])\s+")
_STANCE = re.compile(r"\b(?:we|i)\s+(?:believe|think|feel|hope)\b|\bin\s+(?:our|my)\s+(?:view|opinion)\b|"
                     r"\b(?:we're|we\s+are|i'm|i\s+am)\s+(?:excited|thrilled|proud|delighted|pleased|honou?red|happy)\b", re.I)


def split_sentences(text_: str) -> list[tuple[str, bool]]:
    """Deterministic sentence splitter. Returns (sentence, is_whole_line). Line breaks always split."""
    out: list[tuple[str, bool]] = []
    for line in re.split(r"\r?\n", text_ or ""):
        line = _BULLET.sub("", line).strip()
        if not line:
            continue
        parts, start = [], 0
        for m in _BOUNDARY.finditer(line):
            before = re.findall(r"[A-Za-z]+(?:\.[A-Za-z]+)*", line[start:m.start()])
            last = before[-1].replace(".", "").lower() if before else ""
            if m.group(1).startswith(".") and (last in _ABBR or len(last) == 1):
                continue  # "Inc. announced", "J. Smith", "U.S. markets"
            parts.append(line[start:m.end(1)].strip())
            start = m.end()
        parts.append(line[start:].strip())
        parts = [p for p in parts if p]
        out.extend((p, len(parts) == 1) for p in parts)
    return out


def sentence_hash(sentence: str) -> str:
    return hashlib.sha256(_norm_ws(sentence).encode()).hexdigest()[:16]


def content_tokens(text_: str) -> set[str]:
    out = set()
    for w in _WORD.findall(_URL.sub(" ", (text_ or "").lower()).replace("\u2019", "'")):
        w = w.strip(".-'")
        if w.endswith("'s"):
            w = w[:-2]
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w and w not in _STOP:
            out.add(w)
    return out


def _exempt_reason(sentence: str, whole_line: bool, field: str) -> str:
    """Why a sentence asserts nothing that needs evidence. Deliberately narrow: when unsure, it is an assertion."""
    s = sentence.strip()
    if set(s) <= set("#*-_=~ "):
        return "separator"
    if s.endswith("?"):
        return "question"
    stripped = _PHONE.sub(" ", _EMAIL.sub(" ", _URL.sub(" ", s)))
    toks = content_tokens(stripped)
    if len(toks) <= 1:
        return "label"
    if (_URL.search(s) or _EMAIL.search(s) or _PHONE.search(s)) and len(toks) <= 3:
        return "contact"
    words = re.findall(r"[A-Za-z']+", s)
    if words and words[0].lower() in _CTA and len(words) <= 12 and not numeric_tokens(s):
        return "call_to_action"
    if field == "body" and whole_line and len(words) <= 5 and s[-1] not in ".!:;":
        return "heading"
    return ""


def account(item: ContentItem, claims: list | None = None, dispositions: dict | None = None) -> list[dict]:
    """Sentence-level ledger for one item. Every sentence gets exactly one status:
    exempt | covered | waived | open. `open` is what the gate acts on."""
    claims = json.loads(item.claims_json or "[]") if claims is None else claims
    dispositions = json.loads(item.dispositions_json or "{}") if dispositions is None else dispositions
    supported = []
    for idx, c in enumerate(claims):
        ctype, text_ = c.get("claim_type", "fact"), c.get("text", "")
        ok = (ctype in {"fact", "quote"} and any(valid_source_uri(s.get("uri", "")) for s in (c.get("sources") or []))) \
            or (ctype == "forecast" and bool(_FORECAST_LABEL.search(text_)))
        if ok:
            supported.append((idx, set(c.get("covers") or []), content_tokens(text_)))
    threshold = settings.gate_sentence_match
    ledger, seen = [], set()
    for field in ("title", "summary", "body"):
        for sentence, whole in split_sentences(getattr(item, field) or ""):
            h = sentence_hash(sentence)
            if h in seen:
                continue
            seen.add(h)
            row = {"hash": h, "field": field, "text": sentence, "status": "open", "suggestion": ""}
            reason = _exempt_reason(sentence, whole, field)
            if reason:
                row.update(status="exempt", reason=reason)
            else:
                toks = content_tokens(sentence)
                linked = next((i for i, covers, _ in supported if h in covers), None)
                best_i, best = None, 0.0
                for i, _, ctoks in supported:
                    score = len(toks & ctoks) / len(toks) if toks else 0.0
                    if score > best:
                        best_i, best = i, score
                if linked is not None:
                    row.update(status="covered", claim_index=linked, via="link")
                elif best_i is not None and best >= threshold:
                    row.update(status="covered", claim_index=best_i, via="match", match=round(best, 2))
                elif h in dispositions:
                    d = dispositions[h]
                    row.update(status="waived", disposition=d.get("disposition", ""), by=d.get("by", ""), at=d.get("at", ""))
                else:
                    row["suggestion"] = "opinion" if _STANCE.search(sentence) else "needs_evidence"
            ledger.append(row)
    return ledger


def dispositions_hash(item: ContentItem) -> str:
    """Digest of the reviewer dispositions in force. An approval records it (v1.6.1) so a waiver added by someone who is
    not an approver after the approval cannot silently turn an approved-but-blocked release into a releasable one."""
    try:
        d = json.loads(item.dispositions_json or "{}")
    except ValueError:
        d = {}
    core = {h: {"disposition": v.get("disposition", ""), "text": v.get("text", "")} for h, v in sorted(d.items()) if isinstance(v, dict)}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _text_of(item: ContentItem) -> str:
    return "\n".join([item.title or "", item.summary or "", item.body or ""])


@dataclass
class GateResult:
    passed: bool
    blockers: list[str]
    warnings: list[str]
    checks: dict

    def to_dict(self):
        return asdict(self)


def evaluate(item: ContentItem) -> GateResult:
    claims = json.loads(item.claims_json or "[]")
    approval = json.loads(item.approval_json or "{}")
    cls = item.classification
    high_risk = cls in HIGH_RISK
    evidence_required = high_risk or settings.strict_numeric or cls in settings.evidence_classes
    blockers: list[str] = []
    warnings: list[str] = []

    def flag(msg: str):
        (blockers if evidence_required else warnings).append(msg)

    # 1/2. Declared claims.
    unsupported, unlabeled, supported_text, supported_quote_text = [], [], [], []
    for c in claims:
        ctype, text_ = c.get("claim_type", "fact"), c.get("text", "")
        ok_sources = [s for s in (c.get("sources") or []) if valid_source_uri(s.get("uri", ""))]
        if ctype in {"fact", "quote"}:
            if ok_sources:
                supported_text.append(text_)
                if ctype == "quote":
                    supported_quote_text.append(text_)
            else:
                unsupported.append(text_[:160])
        elif ctype == "forecast":
            if _FORECAST_LABEL.search(text_):
                supported_text.append(text_)
            else:
                unlabeled.append(text_[:160])
        # opinion/internal claims are recorded but never count as evidence.
    if unsupported:
        blockers.append(f"{len(unsupported)} factual/quote claim(s) have no valid source")
    if unlabeled:
        blockers.append(f"{len(unlabeled)} forecast claim(s) are not explicitly labeled as projections/forecasts")

    # 3. Coverage of what the content actually asserts.
    content_text = _text_of(item)
    covered_nums = set().union(*[numeric_tokens(t) for t in supported_text]) if supported_text else set()
    uncovered_nums = sorted(numeric_tokens(content_text) - covered_nums)
    if uncovered_nums:
        flag(f"{len(uncovered_nums)} numeric assertion(s) not covered by a supported claim: {', '.join(uncovered_nums[:8])}")

    quote_evidence = _norm_ws(" ".join(supported_quote_text))
    uncovered_quotes = sorted(q for q in quotations(content_text) if q not in quote_evidence)
    if uncovered_quotes:
        flag(f"{len(uncovered_quotes)} direct quotation(s) not covered by a sourced quote claim")

    covered_sup = set().union(*[superlatives(t) for t in supported_text]) if supported_text else set()
    uncovered_sup = sorted(superlatives(content_text) - covered_sup)
    if uncovered_sup:
        (blockers if high_risk else warnings).append(
            f"superlative/absolute claim(s) without a supported claim: {', '.join(uncovered_sup[:6])}")

    # 5. Sentence accounting: nothing assertive leaves without evidence or a reviewer's decision.
    ledger = account(item, claims)
    open_sentences = [r for r in ledger if r["status"] == "open"]
    if open_sentences and settings.gate_sentence_mode != "off":
        msg = (f"{len(open_sentences)} sentence(s) have neither a supported claim nor a reviewer disposition: "
               + "; ".join('"' + r["text"][:60] + ('…' if len(r["text"]) > 60 else '') + '"' for r in open_sentences[:3]))
        (blockers if evidence_required and settings.gate_sentence_mode == "block" else warnings).append(msg)

    # 4. Human approval, bound to this exact content version.
    current_hash = governed_hash(item)
    has_approval = bool(approval.get("approved_by"))
    hash_current = has_approval and approval.get("content_hash") == current_hash
    # Approvals recorded since v1.6.1 also bind the reviewer dispositions that were in force. Older approvals carry no
    # dispositions_hash and keep their original (content-hash only) semantics.
    dispositions_current = "dispositions_hash" not in approval or approval.get("dispositions_hash") == dispositions_hash(item)
    approval_current = hash_current and dispositions_current
    if high_risk and not approval_current:
        if not has_approval:
            blockers.append(f"human approval required for {cls} content")
        elif not approval.get("content_hash"):
            blockers.append("approval is not bound to a content version (recorded by v1.0); re-approve")
        elif not hash_current:
            blockers.append("approval is stale: content changed after it was approved")
        else:
            blockers.append("approval is stale: sentence dispositions changed after it was approved; re-approve")
    elif has_approval and not approval_current:
        warnings.append("recorded approval is stale: content or dispositions changed after it was approved")

    if not (item.title or "").strip() or not (item.body or "").strip():
        blockers.append("title and body are required")

    return GateResult(
        passed=not blockers, blockers=blockers, warnings=warnings,
        checks={"policy_version": POLICY_VERSION, "classification": cls, "evidence_required": evidence_required,
                "content_hash": current_hash, "claim_count": len(claims), "unsupported_claims": unsupported,
                "unlabeled_forecasts": unlabeled, "uncovered_numeric_assertions": uncovered_nums,
                "uncovered_quotations": [q[:160] for q in uncovered_quotes], "uncovered_superlatives": uncovered_sup,
                "sentences": {k: sum(1 for r in ledger if r["status"] == k) for k in ("exempt", "covered", "waived", "open")},
                "open_sentences": [{"hash": r["hash"], "text": r["text"][:200]} for r in open_sentences],
                "human_approved": bool(approval_current), "approval_stale": bool(has_approval and not approval_current)})


def ungrounded_in(item: ContentItem, generated_text: str) -> list[str]:
    """Deterministic drift check for model output: anything checkable that the derivative
    asserts must already exist in the governed master (content + claims). Returns offenders."""
    claims = json.loads(item.claims_json or "[]")
    master = _text_of(item) + "\n" + "\n".join(c.get("text", "") for c in claims)
    allowed_urls = {u.rstrip(".,);") for u in _URL.findall(master)} | {item.cta_url, item.source}
    bad = [f"number:{n}" for n in sorted(numeric_tokens(generated_text) - numeric_tokens(master))]
    bad += [f"superlative:{s}" for s in sorted(superlatives(generated_text) - superlatives(master))]
    master_n = _norm_ws(master)
    bad += [f"quote:{q[:60]}" for q in sorted(quotations(generated_text)) if q not in master_n]
    bad += [f"url:{u}" for u in sorted({u.rstrip('.,);') for u in _URL.findall(generated_text)} - allowed_urls)]
    # Vocabulary grounding: a generated sentence built mostly from words the master never uses is a new assertion,
    # even when it contains no number, quote or superlative.
    vocab = content_tokens(master)
    for sentence, whole in split_sentences(generated_text):
        if _exempt_reason(sentence, whole, "body"):
            continue
        toks = content_tokens(sentence)
        if toks and len(toks & vocab) / len(toks) < settings.gate_sentence_match:
            bad.append(f"novel:{sentence[:60]}")
    return bad
