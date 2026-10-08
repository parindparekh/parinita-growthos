"""Authority, proof-reuse, reply bounds and identity regressions for v1.8."""
import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.config import ConfigError, Settings, settings
from .conftest import APPROVER, AUDITOR, BOOT, EDITOR, PUBLISHER
from .test_v16 import content, approve


def test_names_cover_all_capabilities_without_occupied_identities(client):
    from app.agents import AGENT_MANIFEST
    from app.agent_names import RESERVED_NAMES
    assert len(AGENT_MANIFEST) == 28
    assert len({a['name'] for a in AGENT_MANIFEST.values()}) == 28
    assert all(a['identity'] not in RESERVED_NAMES for a in AGENT_MANIFEST.values())
    assert [a for a, d in AGENT_MANIFEST.items() if d['can_publish']] == ['feed']
    assert AGENT_MANIFEST['feed']['name'] == 'Parinita GrowthOS Courier'
    assert {'Reach','Compass','Sentinel','Senitene'} <= RESERVED_NAMES
    assert AGENT_MANIFEST['amplify']['identity'] == 'Broadcaster'
    assert AGENT_MANIFEST['aeo']['identity'] == 'Cartographer'
    assert AGENT_MANIFEST['gate']['identity'] == 'Scrutineer'
    assert AGENT_MANIFEST['reddit']['legacy_name'] == 'Parinita Reddit Agent'


@pytest.mark.parametrize('headers,visible', [(EDITOR, True), (BOOT, True), (AUDITOR, False), (PUBLISHER, False), (APPROVER, False)])
def test_contact_email_is_role_restricted(client, headers, visible):
    r = client.post('/v1/media/contacts', headers=EDITOR, json={'provider':'licensed','external_id':'j1','name':'Reporter','email':'private@example.com'})
    assert r.status_code == 201
    rows = client.get('/v1/media/contacts', headers=headers).json()
    assert rows[0]['email'] == ('private@example.com' if visible else '')


@pytest.mark.parametrize('digest,key', [(False,''), (True,''), (False,'key')])
def test_production_chrysalis_cannot_disable_receipt_verification(digest,key):
    s = Settings(environment='production', api_key='a'*40, public_base_url='https://example.com', chrysalis_enabled=True,
                 chrysalis_anchor_url='https://chrysalis.example/anchor', chrysalis_require_receipt_digest=digest,
                 chrysalis_receipt_verify_key=key)
    with pytest.raises(ConfigError, match='requires digest echo'):
        s.validate_runtime()


def configure(monkeypatch,sink):
    monkeypatch.setattr(settings,'chrysalis_enabled',True)
    monkeypatch.setattr(settings,'chrysalis_anchor_url',sink.url+'/chrysalis')
    monkeypatch.setattr(settings,'chrysalis_bearer_token_env','')
    monkeypatch.setattr(settings,'chrysalis_require_receipt_digest',True)
    sink.dynamic = lambda req: (200,{}, {'anchor_id':'chr-bound', 'payload_hash':hashlib.sha256(req['raw']).hexdigest()}) if req['path']=='/chrysalis' else None


def test_cached_attestation_cannot_bypass_revoked_approval(client,sink,lan,monkeypatch):
    from app.chrysalis import anchor_release
    from app.db import SessionLocal
    from app.models import ContentItem
    configure(monkeypatch,sink)
    c = content(client,'investor'); approve(client,c['id'])
    assert client.post(f"/v1/content/{c['id']}/chrysalis/attest",headers=AUDITOR).json()['status']=='anchored'
    with SessionLocal() as db:
        item = db.get(ContentItem,c['id']); item.approval_json='{}'; db.commit()
        with pytest.raises(RuntimeError,match='Gate'):
            anchor_release(db,item)
    assert len(sink.calls('POST','/chrysalis')) == 1


def test_attestation_reuses_unchanged_authority_but_reanchors_new_approval(client,sink,lan,monkeypatch):
    configure(monkeypatch,sink)
    c=content(client,'investor'); approve(client,c['id'])
    path=f"/v1/content/{c['id']}/chrysalis/attest"
    a=client.post(path,headers=AUDITOR).json(); assert a['status']=='anchored'
    b=client.post(path,headers=AUDITOR).json(); assert b['id']==a['id']
    assert len(sink.calls('POST','/chrysalis')) == 1
    approve(client,c['id'])
    d=client.post(path,headers=AUDITOR).json(); assert d['status']=='anchored'
    assert len(sink.calls('POST','/chrysalis')) == 2
    assert d['receipt']['_growthos_release_binding'] != a['receipt']['_growthos_release_binding']


def test_receipt_key_rotation_invalidates_cached_proof(client,sink,lan,monkeypatch):
    configure(monkeypatch,sink)
    c=content(client,'investor'); approve(client,c['id'])
    path=f"/v1/content/{c['id']}/chrysalis/attest"
    assert client.post(path,headers=AUDITOR).json()['status']=='anchored'
    key=ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setattr(settings,'chrysalis_receipt_verify_key',key)
    r=client.post(path,headers=AUDITOR).json()
    assert r['status']=='failed' and 'not signed' in r['error']
    assert len(sink.calls('POST','/chrysalis')) == 2


def test_provider_oversized_reply_never_retries_ambiguous_send(sink,lan,monkeypatch):
    from app.adapters._common import call
    monkeypatch.setattr(settings,'max_feed_bytes',64)
    monkeypatch.setattr(settings,'push_max_attempts',3)
    sink.dynamic=lambda req: (200,{},b'x'*200) if req['path']=='/big' else None
    r,n,error=call('POST',sink.url+'/big',headers={},idempotent=False,json={'title':'approved'})
    assert r is None and n==1 and 'uncertain' in error
    assert len(sink.calls('POST','/big'))==1


@pytest.mark.parametrize('ref',[True, 1, {'id':'fake'}, '   '])
def test_receipt_reference_requires_nonblank_string(ref):
    from app.chrysalis import verify_receipt
    with pytest.raises(RuntimeError,match='reference'):
        verify_receipt({'anchor_id':ref},'0'*64)
