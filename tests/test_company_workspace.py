import pytest
from app.config import settings
from app import sso
from tests.conftest import BOOT, EDITOR


@pytest.mark.parametrize("company", [None,"company-b",["company-a"],123])
def test_foreign_company_tokens_cannot_read_workspace(client,sso_on,monkeypatch,company):
    monkeypatch.setattr(settings,"company_id","company-a")
    token=sso_on.token(org_id=company,groups=["growthos-admin"])
    assert client.get("/v1/feeds",headers={"Authorization":"Bearer "+token}).status_code==401


def test_matching_company_can_sign_in(client,sso_on,monkeypatch):
    monkeypatch.setattr(settings,"company_id","company-a")
    token=sso_on.token(org_id="company-a",groups=["growthos-editor"])
    assert client.get("/v1/content",headers={"Authorization":"Bearer "+token}).status_code==200


def test_old_or_foreign_company_cookie_rejected(monkeypatch):
    monkeypatch.setattr(settings,"company_id","company-a")
    monkeypatch.setattr(settings,"session_secret","a-private-test-signing-key-for-company-test")
    for company in [None,"company-b"]:
        cookie=sso._sign({"company_id":company,"name":"person","roles":["admin"]},60)
        with pytest.raises(sso.SSOError):sso.read_session(cookie)
    assert sso.read_session(sso._sign({"company_id":"company-a"},60))["company_id"]=="company-a"


def test_company_setup_admin_only_and_not_live_certificate(client,monkeypatch):
    monkeypatch.setattr(settings,"company_id","company-a")
    monkeypatch.setattr(settings,"company_name","Company A")
    assert client.get("/v1/workspace/setup",headers=EDITOR).status_code==403
    data=client.get("/v1/workspace/setup",headers=BOOT).json()
    assert data["company_id"]=="company-a"
    assert not data["live_certified"]
    assert data["isolation"]=="dedicated_deployment"
