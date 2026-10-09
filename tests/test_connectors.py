import json
from typing import get_args

import pytest

from app.connectors import catalogue
from app.schemas import Protocol
from tests.conftest import BOOT, EDITOR, AUDITOR


def test_catalogue_covers_every_declared_protocol(client):
    assert client.get('/v1/connectors').status_code == 401
    result = client.get('/v1/connectors', headers=EDITOR).json()
    assert {c['protocol'] for c in result} == set(get_args(Protocol))
    assert len(result) == len(get_args(Protocol))
    assert all(c['implemented'] for c in result)


def endpoint(protocol, config=None):
    return dict(name='Test destination', slug='test-destination', direction='outbound', protocol=protocol,
                url='https://provider.example', config=config or {}, enabled=False)


@pytest.mark.parametrize('spec', catalogue(), ids=lambda c: c['protocol'])
def test_every_catalogue_entry_can_be_configured(client, spec):
    cfg = dict(spec['defaults'])
    for f in spec['fields']:
        if f['required']:
            cfg[f['key']] = 'GROWTHOS_SECRET_TEST' if f['secret_reference'] else '12345'
    cfg.update({'linkedin': {'author_urn': 'urn:li:organization:12345'},
                'x': {'bearer_token_env': 'GROWTHOS_SECRET_TEST'},
                'reddit': {'client_id': 'client123', 'refresh_token_env': 'GROWTHOS_SECRET_TEST'},
                'matrix': {'room_id': '!room:example.com'},
                'pr_wire': {'to': 'desk@example.com'}}.get(spec['protocol'], {}))
    response = client.post('/v1/feeds', headers=BOOT, json=endpoint(spec['protocol'], cfg))
    assert response.status_code == 201, response.text
    assert response.json()['enabled'] is False


def test_readiness_checks_presence_without_sending_or_leaking(client, monkeypatch):
    from app import netguard
    monkeypatch.setattr(netguard, 'safe_request', lambda *a, **k: pytest.fail('readiness must not send'))
    monkeypatch.setenv('GROWTHOS_SECRET_TEST', 'private-token-must-not-appear')
    client.post('/v1/feeds', headers=BOOT, json=endpoint('slack', {'channel': 'C123', 'bearer_token_env': 'GROWTHOS_SECRET_TEST'}))
    assert client.get('/v1/connectors/readiness', headers=AUDITOR).status_code == 403
    r = client.get('/v1/connectors/readiness', headers=BOOT)
    row = r.json()['endpoints'][0]
    assert row['configuration_ready'] and not row['live_verified']
    assert 'private-token-must-not-appear' not in r.text
    monkeypatch.delenv('GROWTHOS_SECRET_TEST')
    row = client.get('/v1/connectors/readiness', headers=BOOT).json()['endpoints'][0]
    assert not row['configuration_ready'] and row['problems']


def test_empty_config_cannot_bypass_validation_on_patch(client):
    ep = client.post('/v1/feeds', headers=BOOT, json=endpoint('slack', {'channel':'C1','bearer_token_env':'GROWTHOS_SECRET_TEST'})).json()
    assert client.patch('/v1/feeds/'+ep['id'], headers=BOOT, json={'config':{}}).status_code == 422
    assert client.get('/v1/feeds', headers=BOOT).json()[0]['config']['channel'] == 'C1'
    assert client.patch('/v1/feeds/'+ep['id'], headers=BOOT, json={'url':None}).status_code == 200


@pytest.mark.parametrize('cfg', [
    {'headers': ['wrong']}, {'bearer_token_env': 123}, {'nested': {'token': 'private'}},
    {'headers': {'Authorization': 'Bearer private'}}, {'items': [{'api_key': 'private'}]},
])
def test_bad_configuration_is_rejected_without_server_error(client, cfg):
    assert client.post('/v1/feeds', headers=BOOT, json=endpoint('webhook', cfg)).status_code == 422


def test_provider_failures_do_not_return_response_body_or_request_url(monkeypatch):
    import httpx
    from app.adapters import _common
    r = httpx.Response(403, text='provider echoed private-token')
    assert 'private-token' not in _common.failure(r, 1, '').detail
    monkeypatch.setattr(_common, 'check_url', lambda url: url)
    def fail(*args, **kwargs):
        raise httpx.ReadTimeout('https://provider.example/private-token')
    monkeypatch.setattr(_common, 'safe_request', fail)
    _, _, err = _common.call('POST', 'https://provider.example', headers={}, idempotent=False)
    assert err == 'ReadTimeout'


@pytest.mark.parametrize('key', ['agent_history', 'vaak', 'editorial_review'])
def test_callers_cannot_forge_server_generated_evidence(client, key):
    payload = {'title':'Title', 'body':'Body', 'metadata':{key: {}}}
    assert client.post('/v1/content', headers=EDITOR, json=payload).status_code == 422
    from tests.conftest import make
    item = make(client)
    assert client.patch('/v1/content/'+item['id'], headers=EDITOR, json={'metadata':{key: {}}}).status_code == 422


def test_errors_redact_referenced_secrets(monkeypatch):
    from app.netguard import redact_destination_error
    monkeypatch.setenv('GROWTHOS_SECRET_TEST', 'private+credential')
    assert redact_destination_error('private+credential private%2Bcredential', {'auth':{'secret_env':'GROWTHOS_SECRET_TEST'}}) == '[redacted] [redacted]'


def test_partial_smtp_refusal_is_not_reported_as_success(monkeypatch):
    from app.adapters import smtp
    from app.config import settings
    monkeypatch.setattr(settings, 'smtp_host', 'mail.example.com')
    monkeypatch.setattr(settings, 'smtp_from', 'news@example.com')
    monkeypatch.setattr(settings, 'smtp_port', 465)
    monkeypatch.setattr(settings, 'smtp_username', '')
    class Server:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def send_message(self, message): return {'refused@example.com': (550, b'private provider detail')}
    monkeypatch.setattr(smtp.smtplib, 'SMTP_SSL', Server)
    result = smtp.send_mail(['ok@example.com','refused@example.com'], 'Subject', 'Body', 'test')
    assert not result.ok and 'reconcile' in result.detail
    assert 'refused@example.com' not in result.detail and 'private provider detail' not in result.detail


@pytest.mark.parametrize('protocol,cfg,status,response', [
    ('devto', {'draft':True}, 201, {'id':'one'}),
    ('ghost', {'draft':True}, 201, {'posts':[{'id':'one'}]}),
    ('buttondown', {'draft':True}, 201, {'id':'one'}),
    ('mailchimp', {'draft':True,'list_id':'one','from_name':'News','reply_to':'news@example.com'}, 200, {'id':'one'}),
    ('shopify', {'draft':True,'blog_id':'one'}, 201, {'article':{'id':'one'}}),
    ('transistor', {'publish':False,'show_id':'one'}, 201, {'data':{'id':'one'}}),
    ('buzzsprout', {'publish':False,'podcast_id':'one'}, 201, {'id':'one'}),
    ('facebook', {'unpublished':True,'page_id':'one'}, 200, {'id':'one'}),
    ('tumblr', {'state':'draft','blog':'example.com'}, 201, {'response':{'id':'one'}}),
    ('tiktok', {'direct_post':False}, 200, {'error':{'code':'ok'},'data':{'publish_id':'one'}}),
])
def test_provider_drafts_and_creator_inbox_are_not_publications(monkeypatch, protocol, cfg, status, response):
    import importlib
    import httpx
    from types import SimpleNamespace
    from app.adapters import REGISTRY
    adapter = REGISTRY[protocol]
    module = importlib.import_module(type(adapter).__module__)
    monkeypatch.setattr(module, 'call', lambda *a, **k: (httpx.Response(status, json=response), 1, ''))
    monkeypatch.setattr(module, 'secret', lambda *a: 'one:'+'ab'*32)
    payload = {'id':'one','content_hash':'a'*64,'title':'Title','body':'Body','summary':'Summary',
               'media':{'audio_url':'https://cdn.example.com/episode.mp3'}, 'metadata':{'image_url':'https://cdn.example.com/image.jpg'}}
    result = adapter.send(payload, SimpleNamespace(url='https://provider.example'), cfg, 'delivery-one')
    assert result.ok, result.detail
    assert result.publishes is False


def test_publishing_html_escapes_attribute_quotes_and_copy():
    from app.adapters.publishing import _html
    result = _html({'body':'<script>bad()</script>', 'cta_url':'https://example.com/" onclick="bad()'}, '<b>Read</b>')
    assert '<script>' not in result and '<b>' not in result
    assert '&quot; onclick=&quot;' in result
