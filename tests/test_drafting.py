from .conftest import EDITOR, AUDITOR
from app import model_runtime
from .conftest import BOOT
from app.editorial import inspect_copy
import pytest


def test_drafting_route_and_model_failure(client, monkeypatch):
    monkeypatch.setattr(model_runtime, "configured", lambda: False)
    assert client.get('/v1/drafting/status', headers=EDITOR).json()['configured'] is False
    payload = {'format': 'email', 'brief': 'Invite the team to a workshop.', 'source_material': 'A team writing workshop is planned.'}
    assert client.post('/v1/drafting/drafts', headers=AUDITOR, json=payload).status_code == 403
    assert client.post('/v1/drafting/drafts', headers=EDITOR, json=payload).status_code == 503
    monkeypatch.setattr(model_runtime, 'configured', lambda: True)
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: ({}, 'deterministic-fallback: timeout'))
    assert client.post('/v1/drafting/drafts', headers=EDITOR, json=payload).status_code == 502


def test_generated_content_is_only_a_draft(client, monkeypatch):
    monkeypatch.setattr(model_runtime, 'configured', lambda: True)
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: ({'title': 'Workshop', 'body': 'Please join our writing workshop.', 'summary': 'Invitation', 'state': 'approved', 'claims': ['fabricated']}, 'model'))
    r = client.post('/v1/drafting/drafts', headers=EDITOR, json={'format': 'email', 'brief': 'Invite the team to a workshop.', 'source_material': 'A team writing workshop is planned.'})
    assert r.status_code == 201, r.text
    assert r.json()['state'] == 'draft'
    assert r.json()['claims'] == []


BRIEF = {'format': 'email', 'brief': 'Invite the team to a workshop.', 'source_material': 'A team writing workshop is planned.'}
OUTPUT = {'title': 'Workshop', 'body': 'Please join our writing workshop.', 'summary': 'Invitation'}


def test_brand_persists_and_is_used_as_style_only(client, monkeypatch):
    assert client.put('/v1/drafting/brand', headers=EDITOR, json={'name': 'Cedar'}).status_code == 403
    assert client.put('/v1/drafting/brand', headers=BOOT, json={'name': 'Cedar', 'voice': 'Direct and kind.', 'excluded_phrases': 'game-changing'}).status_code == 200
    assert client.get('/v1/drafting/brand', headers=EDITOR).json()['name'] == 'Cedar'
    prompts = []
    monkeypatch.setattr(model_runtime, 'configured', lambda: True)
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: (prompts.append(args) or OUTPUT, 'model'))
    r = client.post('/v1/drafting/drafts', headers=EDITOR, json=BRIEF)
    assert r.status_code == 201
    assert 'style only' in prompts[0][0] and 'Direct and kind.' in prompts[0][1]
    assert r.json()['metadata']['drafting']['brand']['name'] == 'Cedar'


def test_campaign_has_four_linked_drafts(client, monkeypatch):
    monkeypatch.setattr(model_runtime, 'configured', lambda: True)
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: (OUTPUT, 'model'))
    r = client.post('/v1/drafting/campaign', headers=EDITOR, json=BRIEF)
    assert r.status_code == 201, r.text
    data = r.json()
    assert {i['content_type'] for i in data['items']} == {'press_release', 'social', 'email', 'podcast'}
    assert all(i['campaign_id'] == data['campaign_id'] and i['state'] == 'draft' for i in data['items'])


def test_campaign_failure_does_not_save_partial_work(client, monkeypatch):
    monkeypatch.setattr(model_runtime, 'configured', lambda: True)
    replies = iter([(OUTPUT, 'model'), ({}, 'deterministic-fallback: timeout')])
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: next(replies))
    assert client.post('/v1/drafting/campaign', headers=EDITOR, json=BRIEF).status_code == 502
    assert client.get('/v1/content', headers=EDITOR).json() == []
    assert client.get('/v1/campaigns', headers=EDITOR).json() == []


def test_revision_preserves_original_and_review_is_hash_bound(client, monkeypatch):
    monkeypatch.setattr(model_runtime, 'configured', lambda: True)
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: (OUTPUT, 'model'))
    first = client.post('/v1/drafting/drafts', headers=EDITOR, json=BRIEF).json()
    second = client.post('/v1/drafting/drafts', headers=EDITOR, json={**BRIEF, 'parent_id': first['id']}).json()
    assert first['id'] != second['id'] and second['metadata']['drafting']['parent_id'] == first['id']
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: ({'findings': []}, 'model'))
    review = client.post('/v1/drafting/'+first['id']+'/review', headers=EDITOR).json()
    changed = client.patch('/v1/content/'+first['id'], headers=EDITOR, json={'body': 'A different workshop description.'}).json()
    assert review['content_hash'] != changed['content_hash']
    assert changed['state'] == 'draft'


def test_invented_review_excerpt_is_rejected(client, monkeypatch):
    monkeypatch.setattr(model_runtime, 'configured', lambda: True)
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: (OUTPUT, 'model'))
    item = client.post('/v1/drafting/drafts', headers=EDITOR, json=BRIEF).json()
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: ({'findings': [{'excerpt': 'invented passage', 'reason': 'check'}]}, 'model'))
    assert client.post('/v1/drafting/'+item['id']+'/review', headers=EDITOR).status_code == 502


def test_editorial_checks_are_specific_and_do_not_claim_truth():
    result = inspect_copy({'title': 'Workshop', 'body': 'Join 500 guests at https://madeup.example. [Your Name] game-changing', 'summary': ''}, 'A workshop.', 'game-changing')
    assert {i['kind'] for i in result['issues']} == {'unsupported_number', 'unsupported_link', 'placeholder', 'brand_language'}
    assert 'Factual accuracy still requires' in result['scope']
    assert inspect_copy({'body': 'November 1, 2026, at 45 minutes.'}, 'November 1, 2026. It lasts 45 minutes.')['issues'] == []
