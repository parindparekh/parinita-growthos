import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import tempfile
import threading
import time
import urllib.parse

# Environment must be set before the app modules are imported.
_tmp = tempfile.mkdtemp(prefix="growthos-test-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["ENVIRONMENT"] = "development"
os.environ["API_KEY"] = "bootstrap-key-for-tests-0000000001"
os.environ["API_KEYS"] = ",".join([
    "erin:editor:editor-key-for-tests-000000000001",
    "ana:approver:approver-key-for-tests-0000000001",
    "pat:publisher:publisher-key-for-tests-000000001",
    "aud:auditor:auditor-key-for-tests-00000000001",
    "eve:editor|approver:editor-approver-key-tests-000001",
])
os.environ["PUSH_BACKOFF_SECONDS"] = "0"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["GROWTHOS_SECRET_HOOK_TOKEN"] = "hook-token-value"
os.environ["GROWTHOS_SECRET_HOOK_SIGNING"] = "hook-signing-secret"
os.environ["SMTP_PASSWORD"] = "must-never-leave-the-process"
os.environ["GROWTHOS_SECRET_LI_TOKEN"] = "li-access-token"
os.environ["GROWTHOS_SECRET_X_CK"] = "x-consumer-key"
os.environ["GROWTHOS_SECRET_X_CS"] = "x-consumer-secret"
os.environ["GROWTHOS_SECRET_X_AT"] = "x-access-token"
os.environ["GROWTHOS_SECRET_X_ATS"] = "x-access-token-secret"
os.environ["GROWTHOS_SECRET_MASTO"] = "masto-token"
os.environ["GROWTHOS_SECRET_BSKY"] = "bsky-app-password"
os.environ["GROWTHOS_SECRET_TRANSISTOR"] = "transistor-key"
os.environ["GROWTHOS_SECRET_BUZZ"] = "buzz-token"
os.environ["GROWTHOS_SECRET_WIRE"] = "wire-partner-key"
os.environ["GROWTHOS_SECRET_SLACK"] = "xoxb-slack-bot-token"
os.environ["GROWTHOS_SECRET_TG"] = "123456:telegram-bot-token"
os.environ["GROWTHOS_SECRET_WP"] = "wp-app-password"
os.environ["GROWTHOS_SECRET_MCP"] = "mcp-server-token"
os.environ["GROWTHOS_SECRET_VAAK"] = "vaak-owner-token"
os.environ["GROWTHOS_SECRET_WA_TOKEN"] = "wa-system-user-token"
os.environ["GROWTHOS_SECRET_WA_LIST"] = "15551230001, 15551230002,15551230003"
for k in ("TEXT_MODEL_BASE_URL", "TEXT_MODEL_NAME", "DESTINATION_ALLOWLIST", "ALLOW_PRIVATE_DESTINATIONS", "OIDC_ISSUER",
          "OIDC_CLIENT_ID", "SESSION_SECRET", "PROVIDER_BASE_OVERRIDES"):
    os.environ.pop(k, None)

import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import init_db  # noqa: E402

BOOT = {"X-API-Key": "bootstrap-key-for-tests-0000000001"}
EDITOR = {"X-API-Key": "editor-key-for-tests-000000000001"}
APPROVER = {"X-API-Key": "approver-key-for-tests-0000000001"}
PUBLISHER = {"X-API-Key": "publisher-key-for-tests-000000001"}
AUDITOR = {"X-API-Key": "auditor-key-for-tests-00000000001"}
EDITOR_APPROVER = {"X-API-Key": "editor-approver-key-tests-000001"}


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def lan(monkeypatch):
    """Permit loopback destinations so tests can talk to the local sink."""
    monkeypatch.setattr(settings, "allow_private_destinations", True)


class Sink:
    """Local HTTP endpoint that records what GrowthOS sends, serves canned feeds, and can impersonate a provider API."""

    def __init__(self):
        self.posts, self.gets, self.routes, self.post_statuses, self.requests, self.replies = [], [], {}, [], [], {}
        self.dynamic = None  # optional callable(request) -> (status, headers, body) for stateful mocks
        sink = self

        class H(http.server.BaseHTTPRequestHandler):
            def _record(self):
                raw = self.rfile.read(int(self.headers.get("content-length", 0) or 0))
                ctype = self.headers.get("content-type", "")
                try:
                    parsed = json.loads(raw) if raw and "json" in ctype else (dict(urllib.parse.parse_qsl(raw.decode())) if raw else {})
                except ValueError:
                    parsed = {}
                req = {"method": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                       "raw": raw, "json": parsed}
                sink.requests.append(req)
                return req

            def _reply(self, status, headers=None, body=b""):
                body = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                if status in (301, 302, 307) and "Location" not in (headers or {}):
                    self.send_header("Location", "http://127.0.0.1:1/internal")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _scripted(self):
                q = sink.replies.get((self.command, self.path.split("?")[0]))
                if not q:
                    return False
                status, headers, body = q.pop(0) if len(q) > 1 else q[0]
                self._reply(status, {"Content-Type": "application/json", **(headers or {})}, body)
                return True

            def do_POST(self):
                req = self._record()
                if sink.dynamic is not None:
                    out = sink.dynamic(req)
                    if out is not None:
                        status, headers, body = out
                        return self._reply(status, headers if isinstance(body, bytes) else {"Content-Type": "application/json", **(headers or {})}, body)
                if self._scripted():
                    return
                sink.posts.append(req)
                self._reply(sink.post_statuses.pop(0) if sink.post_statuses else 200)

            def do_DELETE(self):
                self._record()
                self._reply(204)

            def do_PATCH(self):
                self._record()
                if not self._scripted():
                    self._reply(404)

            def do_PUT(self):
                req = self._record()
                if sink.dynamic is not None:
                    out = sink.dynamic(req)
                    if out is not None:
                        status, headers, body = out
                        return self._reply(status, headers if isinstance(body, bytes) else {"Content-Type": "application/json", **(headers or {})}, body)
                if not self._scripted():
                    self._reply(404)

            def do_GET(self):
                sink.gets.append(self.path)
                status, headers, body = sink.routes.get(self.path, (404, {}, b""))
                self._reply(status, headers, body)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def serve(self, path, body, status=200, headers=None):
        self.routes[path] = (status, headers or {}, body if isinstance(body, bytes) else body.encode())

    def reply(self, method, path, *responses):
        """Script provider responses: each is (status, headers, json_body). The last one repeats."""
        self.replies[(method, path)] = list(responses)

    def calls(self, method, path):
        return [r for r in self.requests if r["method"] == method and r["path"].split("?")[0] == path]


@pytest.fixture()
def sink():
    s = Sink()
    yield s
    s.server.shutdown()


class IdP:
    """Minimal OpenID Connect provider: discovery, JWKS, authorize (auto-consent), token (verifies PKCE + client auth)."""
    client_id, client_secret = "growthos-console", "idp-client-secret"

    def __init__(self):
        self.key, self.kid = rsa.generate_private_key(public_exponent=65537, key_size=2048), "k1"
        self.user = {"sub": "u-1", "email": "ana@corp.example", "email_verified": True, "groups": ["growthos-approver"]}
        self.codes, self.token_requests, self.nonce_override = {}, [], None
        self.access_claims = None  # when set, the access token is a signed JWT carrying these claims (Keycloak layout)
        idp = self

        class H(http.server.BaseHTTPRequestHandler):
            def _json(self, status, obj):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                if u.path == "/.well-known/openid-configuration":
                    self._json(200, {"issuer": idp.url, "authorization_endpoint": idp.url + "/authorize",
                                     "token_endpoint": idp.url + "/token", "jwks_uri": idp.url + "/jwks"})
                elif u.path == "/jwks":
                    self._json(200, idp.jwks())
                elif u.path == "/authorize":
                    code = secrets.token_urlsafe(8)
                    idp.codes[code] = {"nonce": q.get("nonce"), "challenge": q.get("code_challenge"), "user": dict(idp.user),
                                       "redirect_uri": q.get("redirect_uri"), "method": q.get("code_challenge_method")}
                    self.send_response(302)
                    self.send_header("Location", q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": q.get("state", "")}))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._json(404, {})

            def do_POST(self):
                form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers.get("content-length", 0))).decode()))
                idp.token_requests.append({"form": form, "authorization": self.headers.get("Authorization", "")})
                grant = idp.codes.pop(form.get("code", ""), None)
                basic = "Basic " + base64.b64encode(f"{idp.client_id}:{idp.client_secret}".encode()).decode()
                challenge = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                if (grant is None or self.headers.get("Authorization") != basic or grant["method"] != "S256"
                        or challenge != grant["challenge"] or form.get("redirect_uri") != grant["redirect_uri"]):
                    return self._json(400, {"error": "invalid_grant"})
                access = "opaque" if idp.access_claims is None else idp.token(
                    **{"aud": "account", "azp": idp.client_id, "sub": grant["user"].get("sub", "u-1"), **idp.access_claims})
                self._json(200, {"token_type": "Bearer", "access_token": access,
                                 "id_token": idp.token(nonce=idp.nonce_override or grant["nonce"], **grant["user"])})

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def jwks(self):
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def rotate(self):
        self.key, self.kid = rsa.generate_private_key(public_exponent=65537, key_size=2048), "k" + secrets.token_hex(2)

    def token(self, key=None, alg="RS256", kid=None, **claims):
        now = int(time.time())
        body = {"iss": self.url, "aud": self.client_id, "sub": "u-1", "iat": now, "exp": now + 300, **claims}
        return jwt.encode(body, key or self.key, algorithm=alg, headers={"kid": kid or self.kid})


@pytest.fixture()
def idp():
    i = IdP()
    yield i
    i.server.shutdown()


@pytest.fixture()
def sso_on(monkeypatch, idp):
    """Configure the app for SSO against the mock IdP."""
    from app import sso
    monkeypatch.setattr(settings, "oidc_issuer", idp.url)
    monkeypatch.setattr(settings, "oidc_client_id", idp.client_id)
    monkeypatch.setattr(settings, "oidc_client_secret", idp.client_secret)
    monkeypatch.setattr(settings, "session_secret", "s" * 48)
    monkeypatch.setattr(sso, "JWKS_MIN_REFRESH", 0)
    sso.reset_cache()
    yield idp
    sso.reset_cache()


def sso_login(client, idp, **user):
    """Drive the whole code flow through the app and the mock IdP. Returns the CSRF token for the session."""
    idp.user = {**idp.user, **user}
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 302, r.text
    hop = httpx.get(r.headers["location"], follow_redirects=False)  # the "browser" visits the IdP
    back = urllib.parse.urlparse(hop.headers["location"])
    r = client.get(f"{back.path}?{back.query}", follow_redirects=False)
    assert r.status_code == 302, r.text
    return client.get("/auth/me").json()["csrf"]


class SmtpSink:
    """Just enough SMTP to accept one message per connection and keep it."""

    def __init__(self):
        self.messages = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn, conn.makefile("rwb") as f:
                def say(line):
                    f.write(line.encode() + b"\r\n"); f.flush()
                say("220 sink ESMTP")
                rcpt, data = [], None
                while True:
                    line = f.readline()
                    if not line:
                        break
                    cmd = line.decode(errors="replace").strip()
                    up = cmd.upper()
                    if up.startswith(("EHLO", "HELO")):
                        say("250 sink")
                    elif up.startswith("MAIL"):
                        say("250 ok")
                    elif up.startswith("RCPT"):
                        rcpt.append(cmd.split(":", 1)[1].strip(" <>")); say("250 ok")
                    elif up == "DATA":
                        say("354 go")
                        buf = []
                        while (ln := f.readline()) not in (b".\r\n", b""):
                            buf.append(ln)
                        data = b"".join(buf).decode(errors="replace")
                        self.messages.append({"to": rcpt, "data": data})
                        say("250 queued")
                    elif up == "QUIT":
                        say("221 bye"); break
                    else:
                        say("250 ok")


@pytest.fixture()
def smtp_sink(monkeypatch):
    s = SmtpSink()
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", s.port)
    monkeypatch.setattr(settings, "smtp_use_tls", False)
    monkeypatch.setattr(settings, "smtp_from", "newsroom@parinita.example")
    yield s
    s.sock.close()


@pytest.fixture()
def live_server():
    """The real app on a real socket, for browser tests. Same process, so settings patches apply."""
    import uvicorn
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


# ---- helpers shared by test modules -------------------------------------------------
def make(client, **kw):
    """Create content. For evidence classes, a sourced claim covering the title and body is attached unless the
    test passes its own `claims` (pass claims=[] to get an item with unaccounted sentences)."""
    headers = kw.pop("_headers", EDITOR)
    body = {"title": "Launch note", "body": "GrowthOS routes governed content to feed destinations."}
    body.update(kw)
    if body.get("classification", "general") != "general" and "claims" not in kw:
        body["claims"] = [{"text": f"{body['title']}. {body.get('summary', '')} {body['body']}", "sources": SRC}]
    r = client.post("/v1/content", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


SRC = [{"uri": "https://example.com/evidence"}]


def feed(client, **kw):
    r = client.post("/v1/feeds", json=kw, headers=BOOT)
    assert r.status_code == 201, r.text
    return r.json()


def run_pipeline(client, cid):
    r = client.post(f"/v1/content/{cid}/pipeline", headers=EDITOR)
    assert r.status_code == 200, r.text
    return r.json()
