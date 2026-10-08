"""Gate policy 1.2: sentence accounting. Closes the v1.1 gap "the gate cannot see unsourced prose
that carries no number, quote or superlative"."""
import json

import pytest

import app.agents as agents_mod
from app.config import settings
from app.gate import account, evaluate, split_sentences
from app.models import ContentItem
from tests.conftest import APPROVER, AUDITOR, EDITOR, EDITOR_APPROVER, SRC, make, run_pipeline


def item(body, title="T", classification="pr", claims=(), dispositions=None):
    return ContentItem(id="1", content_type="article", title=title, body=body, summary="", locale="en-US", source="", cta_url="",
                       campaign_id=None, classification=classification, approval_json="{}",
                       claims_json=json.dumps(list(claims)), dispositions_json=json.dumps(dispositions or {}))


def statuses(it):
    return {r["text"]: r["status"] for r in account(it)}


@pytest.mark.parametrize("sentence", ["Customers love it.", "The platform is SOC 2 certified.", "Acme Corp. is a launch partner.",
                                      "Our technology was developed with the national laboratory."])
def test_plain_unsourced_prose_is_blocked(sentence):
    # None of these contains a number >= 10, a quotation or a superlative. v1.1 passed every one of them.
    r = evaluate(item(sentence))
    assert not r.passed and r.checks["sentences"]["open"] == 1 and "neither a supported claim" in r.blockers[0]


def test_general_content_warns_and_modes_apply(monkeypatch):
    r = evaluate(item("Customers love it.", classification="general"))
    assert r.passed and any("sentence" in w for w in r.warnings)
    monkeypatch.setattr(settings, "gate_sentence_mode", "warn")
    assert evaluate(item("Customers love it.")).passed
    monkeypatch.setattr(settings, "gate_sentence_mode", "off")
    r = evaluate(item("Customers love it."))
    assert r.passed and not r.warnings


def test_sentence_covered_by_lexical_match_to_a_sourced_claim():
    unrelated = {"text": "The company was founded in Delaware", "sources": SRC}
    assert account(item("The platform is SOC 2 certified.", claims=[unrelated]))[1]["status"] == "open"
    it = item("The platform is SOC 2 certified.", claims=[{"text": "The platform holds a SOC 2 certification", "sources": SRC}])
    row = account(it)[1]
    assert (row["status"], row["via"], row["match"]) == ("covered", "match", 0.75) and evaluate(it).passed
    # The same words in a claim with no source cover nothing.
    assert account(item("The platform is SOC 2 certified.", claims=[{"text": "The platform is SOC 2 certified", "sources": []}]))[1]["status"] == "open"


def test_sentence_covered_by_explicit_link():
    probe = account(item("The platform is SOC 2 certified."))[1]
    linked = {"text": "Type II attestation, March audit", "sources": SRC, "covers": [probe["hash"]]}
    it = item("The platform is SOC 2 certified.", claims=[linked])
    assert (account(it)[1]["status"], account(it)[1]["via"]) == ("covered", "link") and evaluate(it).passed
    # A link from a claim that has no valid source is worth nothing.
    unsourced = {**linked, "sources": []}
    assert account(item("The platform is SOC 2 certified.", claims=[unsourced]))[1]["status"] == "open"
    # An opinion claim never counts as evidence, linked or not.
    opinion = {"text": "The platform is SOC 2 certified.", "claim_type": "opinion", "covers": [probe["hash"]]}
    assert account(item("The platform is SOC 2 certified.", claims=[opinion]))[1]["status"] == "open"


def test_non_assertions_are_exempt():
    body = "Is your pipeline governed?\nLearn more at https://parinita.ai/growthos.\nContact: press@parinita.ai\nAbout Parinita\n###"
    rows = account(item(body))[1:]
    assert [(r["status"], r["reason"]) for r in rows] == [("exempt", "question"), ("exempt", "label"), ("exempt", "label"),
                                                          ("exempt", "label"), ("exempt", "separator")]
    assert account(item("Results\nRegister for the launch webinar today."))[1:] and \
        [r["reason"] for r in account(item("Results overview section\nRegister for the launch webinar today."))[1:]] == ["heading", "call_to_action"]
    assert evaluate(item(body)).passed


def test_splitter_handles_abbreviations_initials_and_decimals():
    text = "Parinita AI Edge Inc. announced GrowthOS v1.2 today. Dr. A. Rao joined the U.S. team. Margin rose 3.5 points."
    assert [s for s, _ in split_sentences(text)] == ["Parinita AI Edge Inc. announced GrowthOS v1.2 today.",
                                                     "Dr. A. Rao joined the U.S. team.", "Margin rose 3.5 points."]


def test_title_is_an_assertion_too():
    r = evaluate(item("###", title="Parinita acquires Boons"))
    assert not r.passed and r.checks["open_sentences"][0]["text"] == "Parinita acquires Boons"


def test_claim_agent_reports_open_sentences_with_suggestions(client):
    cid = make(client, classification="pr", body="We believe governed publishing matters. Customers love it.", claims=[])["id"]
    out = client.post(f"/v1/content/{cid}/agents/run", json={"agent": "claim"}, headers=EDITOR).json()
    assert {s["text"]: s["suggestion"] for s in out["open_sentences"]} == {
        "Launch note": "needs_evidence", "We believe governed publishing matters.": "opinion", "Customers love it.": "needs_evidence"}


# ------------------------------------------------------------------------------ reviewer dispositions
def ledger(client, cid):
    return {s["text"]: s for s in client.get(f"/v1/content/{cid}/assertions", headers=EDITOR).json()["sentences"]}


def test_reviewer_disposition_unblocks_and_is_audited(client):
    cid = make(client, classification="pr", title="Launch note", body="We believe governed publishing matters.", claims=[])["id"]
    assert run_pipeline(client, cid)["state"] == "blocked"
    rows = ledger(client, cid)
    for text in rows:
        h = rows[text]["hash"]
        assert client.put(f"/v1/content/{cid}/assertions/{h}/disposition", json={"disposition": "opinion"}, headers=EDITOR).status_code == 403
        assert client.put(f"/v1/content/{cid}/assertions/{h}/disposition", json={"disposition": "opinion", "note": "stance"}, headers=APPROVER).status_code == 200
    assert {r["status"] for r in ledger(client, cid).values()} == {"waived"}
    assert ledger(client, cid)["Launch note"]["by"] == "ana"
    assert run_pipeline(client, cid)["state"] == "approved"
    ev = [e for e in client.get(f"/v1/audit?content_id={cid}", headers=AUDITOR).json() if e["action"] == "sentence.disposition"]
    assert len(ev) == 2 and ev[0]["actor"] == "ana" and ev[0]["decision"] == "opinion" and ev[0]["details"]["text"]


def test_disposition_is_bound_to_the_sentence_text(client):
    cid = make(client, classification="pr", title="Launch note", body="We believe governed publishing matters.", claims=[])["id"]
    for row in ledger(client, cid).values():
        client.put(f"/v1/content/{cid}/assertions/{row['hash']}/disposition", json={"disposition": "opinion"}, headers=APPROVER)
    assert run_pipeline(client, cid)["state"] == "approved"
    # Swap the opinion for a factual assertion: the old waiver must not carry over.
    client.patch(f"/v1/content/{cid}", json={"body": "Acme Corp. is a launch partner."}, headers=EDITOR)
    rows = ledger(client, cid)
    assert rows["Acme Corp. is a launch partner."]["status"] == "open" and rows["Launch note"]["status"] == "waived"
    assert run_pipeline(client, cid)["state"] == "blocked"


def test_disposition_edge_cases(client, monkeypatch):
    cid = make(client, classification="pr", body="Customers love it.\nIs it governed?", claims=[])["id"]
    rows = ledger(client, cid)
    assert client.put(f"/v1/content/{cid}/assertions/{'0' * 16}/disposition", json={"disposition": "opinion"}, headers=APPROVER).status_code == 404
    q = rows["Is it governed?"]["hash"]
    assert client.put(f"/v1/content/{cid}/assertions/{q}/disposition", json={"disposition": "opinion"}, headers=APPROVER).status_code == 409
    h = rows["Customers love it."]["hash"]
    assert client.put(f"/v1/content/{cid}/assertions/{h}/disposition", json={"disposition": "true"}, headers=APPROVER).status_code == 422
    client.put(f"/v1/content/{cid}/assertions/{h}/disposition", json={"disposition": "opinion"}, headers=APPROVER)
    assert client.delete(f"/v1/content/{cid}/assertions/{h}/disposition", headers=APPROVER).status_code == 200
    assert ledger(client, cid)["Customers love it."]["status"] == "open"
    monkeypatch.setattr(settings, "gate_waiver_role", "editor")
    assert client.put(f"/v1/content/{cid}/assertions/{h}/disposition", json={"disposition": "opinion"}, headers=EDITOR).status_code == 200


def test_four_eyes_applies_to_waivers_on_high_risk_content(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    cid = client.post("/v1/content", json={"title": "Outlook", "body": "Demand remains healthy.", "classification": "investor"},
                      headers=EDITOR_APPROVER).json()["id"]
    h = ledger(client, cid)["Demand remains healthy."]["hash"]
    r = client.put(f"/v1/content/{cid}/assertions/{h}/disposition", json={"disposition": "opinion"}, headers=EDITOR_APPROVER)
    assert r.status_code == 403 and "four-eyes" in r.json()["detail"]
    assert client.put(f"/v1/content/{cid}/assertions/{h}/disposition", json={"disposition": "opinion"}, headers=APPROVER).status_code == 200


def test_high_risk_needs_both_sentence_accounting_and_approval(client):
    cid = make(client, classification="investor", title="Outlook", body="Demand remains healthy.", claims=[])["id"]
    assert client.post(f"/v1/content/{cid}/approve", json={}, headers=APPROVER).json()["state"] == "blocked"  # approved, but sentences open
    for row in ledger(client, cid).values():
        client.put(f"/v1/content/{cid}/assertions/{row['hash']}/disposition", json={"disposition": "opinion"}, headers=APPROVER)
    assert run_pipeline(client, cid)["state"] == "approved"


# ------------------------------------------------------------------------------ model drift
def test_model_copy_that_adds_plain_new_prose_is_rejected(client, monkeypatch):
    cid = make(client, body="GrowthOS routes governed content to feed destinations.")["id"]
    monkeypatch.setattr(agents_mod, "generate_json", lambda s, u, f: (
        {"posts": [{"channel": "x", "copy": "GrowthOS routes governed content. Trusted by leading banks and certified by regulators."}]}, "model"))
    r = client.post(f"/v1/content/{cid}/agents/run", json={"agent": "amplify", "options": {"channels": ["x"]}}, headers=EDITOR).json()
    assert r["generation_mode"].startswith("deterministic-fallback")
    assert any(x.startswith("novel:Trusted by leading banks") for x in r["rejected_ungrounded"])
