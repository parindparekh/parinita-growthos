import pytest
from cryptography.fernet import Fernet
from app.config import settings
from app.db import SessionLocal
from app.models import ConnectorCredential
from app.netguard import secret_from_env, DestinationBlocked
from tests.conftest import BOOT, EDITOR


@pytest.fixture
def vault(monkeypatch):
    monkeypatch.setattr(settings,"connector_encryption_key",Fernet.generate_key().decode())
    monkeypatch.setattr(settings,"company_id","company-a")


def test_encrypted_roundtrip_and_no_value_readback(client,vault):
    name="GROWTHOS_SECRET_ACCOUNT_TEST"; value="private-company-account-token"
    r=client.put("/v1/connector-credentials",headers=BOOT,json={"name":name,"value":value})
    assert r.status_code==200 and value not in r.text
    assert secret_from_env(name)==value
    assert value not in client.get("/v1/connector-credentials",headers=BOOT).text
    with SessionLocal() as db:
        row=db.get(ConnectorCredential,name)
        assert value not in row.encrypted_value
    assert client.delete("/v1/connector-credentials/"+name,headers=BOOT).status_code==200
    assert secret_from_env(name)==""


def test_vault_admin_only(client,vault):
    for method in ["get","put","delete"]:
        route="/v1/connector-credentials"+("/GROWTHOS_SECRET_ACCOUNT_TEST" if method=="delete" else "")
        kwargs={"json":{"name":"GROWTHOS_SECRET_ACCOUNT_TEST","value":"test"}} if method=="put" else {}
        assert getattr(client,method)(route,headers=EDITOR,**kwargs).status_code==403


def test_wrong_company_cannot_decrypt_saved_credential(client,vault,monkeypatch):
    name="GROWTHOS_SECRET_ACCOUNT_TEST"
    client.put("/v1/connector-credentials",headers=BOOT,json={"name":name,"value":"private-token"})
    monkeypatch.setattr(settings,"company_id","company-b")
    with pytest.raises(DestinationBlocked,match="cannot be unlocked"):
        secret_from_env(name)


def test_no_storage_key_does_not_store_plaintext(client,monkeypatch):
    monkeypatch.setattr(settings,"connector_encryption_key","")
    assert client.put("/v1/connector-credentials",headers=BOOT,json={"name":"GROWTHOS_SECRET_ACCOUNT_TEST","value":"private"}).status_code==503
    with SessionLocal() as db:assert db.query(ConnectorCredential).count()==0


def test_server_managed_credentials_are_not_silently_overridden(client,vault,monkeypatch):
    monkeypatch.setenv("GROWTHOS_SECRET_ACCOUNT_TEST","managed-value")
    assert client.put("/v1/connector-credentials",headers=BOOT,json={"name":"GROWTHOS_SECRET_ACCOUNT_TEST","value":"different"}).status_code==409
