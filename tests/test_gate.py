"""Hallucination Gate policy. Each v1.0 bypass has a regression test here."""
import json

import pytest

from app.config import settings
from app.content import governed_hash
from app.gate import evaluate, numeric_tokens
from app.models import ContentItem
from tests.conftest import SRC


def item(**kw):
    base = dict(id="1", content_type="article", title="T", body="A plain statement", summary="", locale="en-US", source="",
                cta_url="", campaign_id=None, classification="general", claims_json="[]", approval_json="{}")
    claims = kw.pop("claims", None)
    base.update(kw)
    if claims is not None:
        base["claims_json"] = json.dumps(claims)
    return ContentItem(**base)


def approved(it):
    it.approval_json = json.dumps({"approved_by": "ana", "content_hash": governed_hash(it)})
    return it


def test_unsourced_fact_blocks():
    assert not evaluate(item(claims=[{"text": "Revenue was $5M", "claim_type": "fact", "sources": []}])).passed


def test_sourced_fact_passes():
    assert evaluate(item(claims=[{"text": "A sourced fact", "claim_type": "fact", "sources": SRC}])).passed


def test_junk_source_uri_is_not_evidence():
    r = evaluate(item(claims=[{"text": "We are the largest", "claim_type": "fact", "sources": [{"uri": "x"}]}]))
    assert not r.passed and r.checks["unsupported_claims"]


@pytest.mark.parametrize("cls", ["investor", "regulated", "legal", "health", "financial"])
def test_every_high_risk_class_needs_approval(cls):
    r = evaluate(item(classification=cls))
    assert not r.passed and any("human approval required" in b for b in r.blockers)


def test_pr_with_undeclared_numbers_is_blocked():
    # v1.0: passed with zero warnings because the scanner never matched "40% " and claims were optional.
    r = evaluate(item(classification="pr", body="Revenue grew 40% last year. We operate 101 POPs in 42 states."))
    assert not r.passed
    assert set(r.checks["uncovered_numeric_assertions"]) == {"40%", "101", "42"}


def test_numbers_covered_by_sourced_claims_pass():
    claims = [{"text": "Revenue grew 40 percent last year", "claim_type": "fact", "sources": SRC},
              {"text": "101 POPs across 42 states", "claim_type": "fact", "sources": SRC}]
    assert evaluate(item(classification="pr", body="Revenue grew 40% last year. We operate 101 POPs in 42 states.", claims=claims)).passed


def test_general_content_warns_instead_of_blocking(monkeypatch):
    r = evaluate(item(body="Attendance reached 5,000 people."))
    assert r.passed and r.warnings
    monkeypatch.setattr(settings, "strict_numeric", True)
    assert not evaluate(item(body="Attendance reached 5,000 people.")).passed


def test_unrelated_opinion_claim_does_not_disable_scan():
    # v1.0: any attached claim (even an opinion) switched the numeric check off for investor content.
    it = approved(item(classification="investor", body="Revenue was $50M and margin 80%.",
                       claims=[{"text": "We feel good", "claim_type": "opinion"}]))
    r = evaluate(it)
    assert not r.passed and set(r.checks["uncovered_numeric_assertions"]) == {"50m", "80%"}


def test_forecast_needs_real_projection_language():
    # v1.0 accepted this because the noun "project" matched the label regex.
    bad = evaluate(item(claims=[{"text": "The project will reach $1B revenue in 2027", "claim_type": "forecast"}]))
    good = evaluate(item(claims=[{"text": "We expect to reach $1B revenue in 2027", "claim_type": "forecast"}]))
    assert not bad.passed and good.passed


def test_quotation_requires_sourced_quote_claim():
    body = 'The CEO said "we are extremely pleased with this quarter" on the call.'
    assert not evaluate(item(classification="pr", body=body)).passed
    claims = [{"text": "CEO: we are extremely pleased with this quarter", "claim_type": "quote", "sources": SRC}]
    assert evaluate(item(classification="pr", body=body, claims=claims)).passed


def test_superlatives_warn_or_block_by_risk():
    assert evaluate(item(body="We are the #1 platform.")).warnings
    assert any("superlative" in b for b in evaluate(approved(item(classification="financial", body="We are the #1 platform."))).blockers)


def test_title_and_summary_are_scanned():
    r = evaluate(item(classification="pr", title="Up 300%", body="Good news."))
    assert not r.passed


@pytest.mark.parametrize("text", ["Launching October 14, 2026 at 10:30", "Released v1.1 and 2.0.3", "See https://x.io/p/12345",
                                  "Founded in 2019", "Uses SHA-256 and ML-DSA-87", "Three steps and 7 agents"])
def test_non_assertions_are_not_flagged(text):
    assert numeric_tokens(text) == set()


@pytest.mark.parametrize("text,token", [("grew 40% last", "40%"), ("up 12.5%.", "12.5%"), ("$1.66B raise", "1.66b"),
                                        ("5 million users", "5m"), ("10x faster", "10x"), ("€2.5 billion", "2.5b"),
                                        ("1,250,000 seats", "1250000"), ("25 bps", "25bps")])
def test_assertions_are_detected(text, token):
    assert token in numeric_tokens(text)


def test_approval_is_bound_to_content_hash():
    it = approved(item(classification="investor"))
    assert evaluate(it).passed
    it.body = "A different statement entirely"
    r = evaluate(it)
    assert not r.passed and r.checks["approval_stale"] and any("stale" in b for b in r.blockers)


def test_empty_body_blocks():
    assert not evaluate(item(body="  ")).passed
