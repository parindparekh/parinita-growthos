import httpx
import pytest
from app import short_video
from app.adapters.social_more import TikTokAdapter
from app.adapters import social_more
from app import netguard


def test_missing_renderer_is_actionable(monkeypatch):
    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    monkeypatch.setattr(short_video.shutil,"which",lambda _:None)
    with pytest.raises(ValueError,match="FFmpeg"):
        short_video.render_short_video({"title":"Test"})


def test_video_upload_not_marked_published(monkeypatch):
    monkeypatch.setattr(short_video,"render_short_video",lambda _:b"synthetic mp4")
    monkeypatch.setenv("GROWTHOS_SECRET_TIKTOK","synthetic-token")
    calls=[]
    def init(method,url,**kwargs):
        assert url.endswith("/inbox/video/init/")
        assert kwargs["json"]["source_info"]["video_size"]==13
        return httpx.Response(200,json={"error":{"code":"ok"},"data":{"publish_id":"test-id","upload_url":"https://open-upload.tiktokapis.com/video/test"}}),1,""
    monkeypatch.setattr(social_more,"call",init)
    def upload(method,url,**kwargs):
        calls.append(method)
        assert "Authorization" not in kwargs["headers"]
        assert kwargs["content"]==b"synthetic mp4"
        return httpx.Response(201)
    monkeypatch.setattr(netguard,"safe_request",upload)
    result=TikTokAdapter().send({},None,{"media_type":"video","access_token_env":"GROWTHOS_SECRET_TIKTOK"},"test")
    assert result.ok and not result.publishes and calls==["PUT"]


def test_rejects_untrusted_upload_host(monkeypatch):
    monkeypatch.setattr(short_video,"render_short_video",lambda _:b"synthetic")
    monkeypatch.setenv("GROWTHOS_SECRET_TIKTOK","synthetic-token")
    monkeypatch.setattr(social_more,"call",lambda *a,**k:(httpx.Response(200,json={"error":{"code":"ok"},"data":{"publish_id":"id","upload_url":"https://evil.example/upload"}}),1,""))
    monkeypatch.setattr(netguard,"safe_request",lambda *a,**k:pytest.fail("Untrusted upload"))
    assert not TikTokAdapter().send({},None,{"media_type":"video","access_token_env":"GROWTHOS_SECRET_TIKTOK"},"test").ok


def test_video_preview_requires_identity(client):
    assert client.post("/v1/content/unknown/video").status_code==401
