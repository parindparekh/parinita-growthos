"""Parinita Vaak integration: approved copy -> governed voice session -> audio + manifest hash -> podcast distribution.

The mock below implements the vaakd owner API routes of the reference daemon (open session, speak -> audio/L16,
close -> manifest, anchor). It is a contract test: it proves GrowthOS calls Vaak correctly and handles refusals,
not that a particular vaakd build accepts it."""
import hashlib
import io
import json
import struct
import wave
import xml.etree.ElementTree as ET

import pytest

from app.config import settings
from tests.conftest import BOOT, EDITOR, PUBLISHER, feed, make, run_pipeline

COPY = "Parinita today announced GrowthOS.\nDetails are at https://parinita.example/growthos for readers.\n###"


class MockVaakd:
    def __init__(self, refuse_open="", refuse_after=None):
        self.sessions, self.spoken, self.closed, self.anchored = {}, [], [], 0
        self.refuse_open, self.refuse_after = refuse_open, refuse_after

    def __call__(self, req):
        parts = [p for p in req["path"].split("/") if p]
        body = req["json"]
        if parts[:1] == ["twins"] and parts[2:] == ["sessions"]:
            if self.refuse_open:
                return 403, {}, {"error": self.refuse_open}
            sid = f"s{len(self.sessions) + 1}"
            self.sessions[sid] = {"twin": parts[1], "open": body, "digest": hashlib.sha256()}
            return 200, {}, {"session_id": sid}
        if parts[:1] == ["sessions"] and parts[2:] == ["speak"]:
            if self.refuse_after is not None and len(self.spoken) >= self.refuse_after:
                return 403, {}, {"error": "SessionError: policy refused this utterance"}
            self.spoken.append(body)
            pcm = struct.pack("<1600h", *([1000] * 1600))            # 100 ms of 16 kHz mono per utterance
            self.sessions[parts[1]]["digest"].update(pcm)
            return 200, {"Content-Type": "audio/L16;rate=16000"}, pcm
        if parts[:1] == ["sessions"] and parts[2:] == ["close"]:
            self.closed.append(parts[1])
            s = self.sessions[parts[1]]
            return 200, {}, {"twin_id": s["twin"], "session_id": parts[1], "verb": s["open"]["verb"], "channel": s["open"]["channel"],
                             "content_digest": s["digest"].hexdigest(), "manifest_hash": "ab" * 32}
        if parts == ["anchor"]:
            self.anchored += 1
            return 200, {}, {"root": "cd" * 32, "count": 1}
        return 404, {}, {"error": "no such endpoint"}


@pytest.fixture()
def vaak(monkeypatch, sink, lan, tmp_path):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path / "media"))
    sink.dynamic = mock = MockVaakd()
    return mock


def voice(client, sink, **over):
    cfg = {"twin_id": "newsroom-voice", "register": "professional", "bearer_token_env": "GROWTHOS_SECRET_VAAK", **over}
    return feed(client, name="Newsroom voice", slug="vaak", direction="outbound", protocol="vaak", url=sink.url, config=cfg)


def approved(client, **kw):
    kw.setdefault("classification", "pr")
    kw.setdefault("title", "Parinita launches GrowthOS")
    kw.setdefault("body", COPY)
    c = make(client, **kw)
    assert run_pipeline(client, c["id"])["state"] == "approved"
    return c["id"]


def render(client, cid, ep):
    return client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": ep["id"]}, headers=PUBLISHER)


def test_approved_copy_is_rendered_and_bound_to_the_vaak_manifest(client, sink, vaak):
    cid, ep = approved(client), voice(client, sink)
    r = render(client, cid, ep)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["provider_id"] == "manifest:" + "ab" * 32 and out["published"] is False
    item = client.get(f"/v1/content/{cid}", headers=EDITOR).json()
    assert item["state"] == "approved"                                   # rendering audio is not sending the release
    meta = item["metadata"]
    assert meta["vaak"] == {"twin_id": "newsroom-voice", "session_id": "s1", "manifest_hash": "ab" * 32, "anchored_root": "cd" * 32,
                            "content_digest": vaak.sessions["s1"]["digest"].hexdigest(), "rendered_hash": item["content_hash"]}
    assert meta["audio_type"] == "audio/wav" and meta["audio_duration"] == "00:00" and meta["audio_url"].endswith(f"/media/{cid}/{item['content_hash'][:12]}.wav")
    # What Vaak was asked to do.
    assert vaak.sessions["s1"]["open"] == {"verb": "speak_public", "channel": "local", "language": "en", "presence_checked": False, "register": "professional"}
    assert [s["text"] for s in vaak.spoken] == ["Parinita launches GrowthOS", "Parinita today announced GrowthOS.", "Details are at  for readers."]
    assert vaak.closed == ["s1"] and vaak.anchored == 1
    assert all(q["headers"]["authorization"] == "Bearer vaak-owner-token" for q in sink.requests)
    # The audio GrowthOS serves is exactly what Vaak produced: same bytes its manifest digest covers.
    audio = client.get(f"/media/{cid}/{item['content_hash'][:12]}.wav")
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(audio.content)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 4800)
        assert hashlib.sha256(w.readframes(w.getnframes())).hexdigest() == meta["vaak"]["content_digest"]
    assert render(client, cid, ep).json()["duplicate"] is True
    assert len(vaak.sessions) == 1                                       # same version is never rendered twice


def test_audio_is_withdrawn_when_the_release_changes(client, sink, vaak):
    cid = approved(client)
    render(client, cid, voice(client, sink))
    url = client.get(f"/v1/content/{cid}", headers=EDITOR).json()["metadata"]["audio_url"]
    path = url[url.index("/media/"):]
    assert client.get(path).status_code == 200
    client.patch(f"/v1/content/{cid}", json={"body": "Parinita today announced GrowthOS. Customers love it."}, headers=EDITOR)
    assert client.get(path).status_code == 404                           # old audio no longer matches an approved version
    assert client.get("/media/../etc/passwd").status_code == 404 and client.get(f"/media/{cid}/nothex.wav").status_code == 404


def test_vaak_refusals_are_reported_and_sessions_are_never_left_open(client, sink, vaak):
    cid, ep = approved(client), voice(client, sink)
    vaak.refuse_open = "EnvelopeError: speak_public not granted by envelope (deny-by-default)"
    r = render(client, cid, ep)
    assert r.status_code == 502 and "Vaak refused to open a voice session: EnvelopeError: speak_public not granted" in r.json()["detail"]
    vaak.refuse_open, vaak.refuse_after = "", 1
    r = render(client, cid, ep)
    assert r.status_code == 502 and "Vaak refused to speak this copy: SessionError: policy refused" in r.json()["detail"]
    assert vaak.closed == ["s1"]                                         # closed after the refusal: the manifest records what was said
    meta = client.get(f"/v1/content/{cid}", headers=EDITOR).json()["metadata"]
    assert "audio_url" not in meta and "vaak" not in meta                # partial audio is never attached or served


def test_gate_runs_before_vaak_and_config_is_validated(client, sink, vaak, monkeypatch):
    ep = voice(client, sink)
    blocked = make(client, classification="pr", body="Customers love it.", claims=[])["id"]
    assert render(client, blocked, ep).status_code == 409 and sink.requests == []      # unsourced copy never reaches the voice
    monkeypatch.setattr(settings, "media_dir", "")
    assert "MEDIA_DIR is not configured" in render(client, approved(client), ep).json()["detail"]
    base = {"name": "n", "slug": "v2", "direction": "outbound", "protocol": "vaak", "url": "http://vaakd.pop.internal:8477"}
    assert "twin_id" in client.post("/v1/feeds", json={**base, "config": {}}, headers=BOOT).json()["detail"]
    assert "config.routes may only override" in client.post("/v1/feeds", json={**base, "config": {"twin_id": "t", "routes": {"erase": "/x"}}}, headers=BOOT).json()["detail"]
    assert client.post("/v1/feeds", json={**base, "url": "", "config": {"twin_id": "t"}}, headers=BOOT).status_code == 422


def test_call_channel_discloses_and_routes_can_be_overridden(client, sink, vaak):
    ep = voice(client, sink, verb="telephony_speak", channel="call", routes={"anchor": "/v2/anchor"}, anchor=True, prosody={"pace": "unhurried"})
    r = render(client, approved(client), ep)
    assert r.status_code == 200 and "anchoring did not confirm" in r.json()["detail"]          # /v2/anchor does not exist on this daemon
    paths = [q["path"] for q in sink.requests]
    assert paths[0] == "/twins/newsroom-voice/sessions" and paths[1] == "/sessions/s1/disclose" and paths[-1] == "/v2/anchor"
    assert vaak.spoken[0]["prosody"] == {"pace": "unhurried"}


def test_rendered_audio_flows_into_podcast_rss_and_podcast_hosts(client, sink, vaak, monkeypatch):
    cid = approved(client)
    render(client, cid, voice(client, sink))
    audio_url = client.get(f"/v1/content/{cid}", headers=EDITOR).json()["metadata"]["audio_url"]
    feed(client, name="Show", slug="show", direction="outbound", protocol="podcast_rss", config={"classifications": ["pr"]})
    enclosure = ET.fromstring(client.get("/feeds/show").text).find("channel/item/enclosure")
    assert enclosure.attrib["url"] == audio_url and enclosure.attrib["type"] == "audio/wav" and int(enclosure.attrib["length"]) > 44
    # A podcast host adapter picks the same audio up.
    monkeypatch.setattr(settings, "provider_base_overrides", json.dumps({"buzzsprout": sink.url}))
    sink.dynamic = None
    sink.reply("POST", "/api/1/episodes.json", (201, {}, {"id": 5}))
    host = feed(client, name="Host", slug="host", direction="outbound", protocol="buzzsprout", config={"api_token_env": "GROWTHOS_SECRET_BUZZ", "podcast_id": "1", "classifications": ["pr"]})
    r = client.post(f"/v1/content/{cid}/publish", json={"endpoint_id": host["id"]}, headers=PUBLISHER)
    assert r.status_code == 200 and r.json()["published"] is True
    assert sink.calls("POST", "/api/1/episodes.json")[0]["json"]["audio_url"] == audio_url
