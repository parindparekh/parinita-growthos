from types import SimpleNamespace
import httpx
from app.adapters.ai_studio import AIStudioAdapter
from app.adapters import ai_studio


def test_company_token_and_script_handoff(monkeypatch):
    monkeypatch.setenv("GROWTHOS_SECRET_COMPANY_A_STUDIO", "company-a-token")
    seen=[]
    def call(method,url,**kwargs):
        assert kwargs["headers"]["Authorization"]=="Bearer company-a-token"
        assert not kwargs["idempotent"]
        seen.append(url)
        if url.endswith("/api/projects"):
            return httpx.Response(201,json={"id":"project_a"}),1,""
        assert kwargs["json"]["text"]=="The complete approved podcast script."
        assert kwargs["json"]["expected_version"]==0
        return httpx.Response(200,json={"graph":{"version":1}}),1,""
    monkeypatch.setattr(ai_studio,"call",call)
    r=AIStudioAdapter().send({"title":"Episode","body":"The complete approved podcast script."},SimpleNamespace(url="https://studio.example"),{"bearer_token_env":"GROWTHOS_SECRET_COMPANY_A_STUDIO"},"delivery")
    assert r.ok and not r.publishes and r.provider_id=="project_a"
    assert len(seen)==2 and all("produce" not in u for u in seen)


def test_script_failure_keeps_project_for_retry(monkeypatch):
    monkeypatch.setenv("GROWTHOS_SECRET_STUDIO", "test-token")
    seen=[]
    def call(method,url,**kwargs):
        seen.append(url)
        if url.endswith("/api/projects"):
            return httpx.Response(201,json={"id":"project_a"}),1,""
        return httpx.Response(503,text="private-token"),1,""
    monkeypatch.setattr(ai_studio,"call",call)
    adapter=AIStudioAdapter(); ep=SimpleNamespace(url="https://studio.example")
    cfg={"bearer_token_env":"GROWTHOS_SECRET_STUDIO"}; payload={"body":"A sufficiently long script."}
    r=adapter.send(payload,ep,cfg,"delivery")
    assert not r.ok and r.provider_id=="project_a" and "private-token" not in r.detail
    adapter.send(payload,ep,cfg,"delivery",resume=r.provider_id)
    assert sum(u.endswith("/api/projects") for u in seen)==1


def test_invalid_resume_cannot_change_request_path(monkeypatch):
    monkeypatch.setenv("GROWTHOS_SECRET_STUDIO", "test-token")
    monkeypatch.setattr(ai_studio,"call",lambda *a,**k: (_ for _ in ()).throw(AssertionError("No request expected")))
    r=AIStudioAdapter().send({"body":"A sufficiently long script."},SimpleNamespace(url="https://studio.example"),{"bearer_token_env":"GROWTHOS_SECRET_STUDIO"},"delivery",resume="../../other")
    assert not r.ok
