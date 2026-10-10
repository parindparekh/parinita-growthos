"""Growth Command, driven in a real headless browser against the real app on a real socket.
Skipped automatically where Playwright/Chromium is not installed."""
import os

import pytest

pw = pytest.importorskip("playwright.sync_api")

from app.config import settings  # noqa: E402
from tests.conftest import BOOT, EDITOR, feed, make  # noqa: E402

SHOTS = os.environ.get("CONSOLE_SCREENSHOTS", "")
COPY = ("Parinita today announced GrowthOS, a control plane for governed releases.\nCustomers love it.\n"
        "We believe governed publishing matters.\nIs your release pipeline governed?")


@pytest.fixture(scope="module")
def browser():
    try:
        p = pw.sync_playwright().start()
        b = p.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no headless browser available: {exc}")
    yield b
    b.close()
    p.stop()


@pytest.fixture()
def page(browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.console_errors = []
    pg.on("console", lambda m: pg.console_errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: pg.console_errors.append(str(e)))
    yield pg
    ctx.close()


def sign_in_with_key(page, base, key):
    page.goto(base + "/console")
    page.get_by_label("Access key").fill(key)
    page.get_by_role("button", name="Sign in with an access key").click()
    page.get_by_role("navigation", name="Sections").wait_for()


def shot(page, name):
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, name), full_page=True)


def line(page, text):
    return page.locator(".line", has_text=text).first


def test_blocked_release_is_cleared_and_sent_from_the_console(client, live_server, page, sink, lan):
    cid = make(client, classification="pr", title="Parinita launches GrowthOS", body=COPY, claims=[], cta_url="https://parinita.example/growthos")["id"]
    feed(client, name="Newsroom webhook", slug="newsroom", direction="outbound", protocol="webhook", url=sink.url + "/hook")
    sign_in_with_key(page, live_server, BOOT["X-API-Key"])

    page.get_by_role("button", name="Parinita launches GrowthOS").click()
    page.locator(".line.title").wait_for()
    assert page.locator(".line.open").count() == 4 and page.locator(".line.exempt").count() == 1   # the question needs nothing
    assert page.get_by_role("button", name="Send", exact=True).is_disabled()

    # A sentence with no number, quote or superlative: add evidence for it. The source is typed while "Run checks"
    # is still in flight; when the checks finish and the page repaints, what was typed must still be there.
    line(page, "Customers love it.").get_by_role("button").click()
    page.get_by_role("button", name="Run checks").click()
    page.get_by_label("Source", exact=True).fill("internal://csat-survey-2026-q3")
    page.get_by_text("Checks finished.").wait_for()
    assert page.get_by_text("Blocked", exact=True).first.is_visible()
    assert page.get_by_label("Source", exact=True).input_value() == "internal://csat-survey-2026-q3"
    page.get_by_role("button", name="Add evidence").click()
    page.locator(".line.covered", has_text="Customers love it.").wait_for()
    assert line(page, "Customers love it.").locator(".mark").inner_text() == "\u00a71"

    # An opinion: a reviewer lets it stand.
    line(page, "We believe governed publishing matters.").get_by_role("button").click()
    assert page.get_by_text("This reads as a statement of opinion.").is_visible()
    page.get_by_role("button", name="Let it stand").click()
    page.locator(".line.waived", has_text="We believe").wait_for()
    assert line(page, "We believe").locator(".mark").inner_text() == "stet"
    shot(page, "console-proof.png")

    for text in ("Parinita launches GrowthOS", "Parinita today announced GrowthOS"):
        page.locator(".line.open", has_text=text).first.get_by_role("button").click()
        page.get_by_label("Source", exact=True).fill("https://parinita.example/newsroom/launch-brief")
        page.get_by_role("button", name="Add evidence").click()
        page.locator(".line.open", has_text=text).wait_for(state="detached")
    page.get_by_role("button", name="Run checks").click()
    page.get_by_text("Checks finished.").wait_for()
    assert page.get_by_text("Clear to release").is_visible()

    assert page.get_by_role("tab", name="Ready").get_attribute("aria-selected") == "true"   # the queue followed the release
    assert page.get_by_role("button", name="Parinita launches GrowthOS").is_visible()
    page.locator("[data-send=newsroom]").click()
    page.get_by_text("Sent to Newsroom webhook.").wait_for()
    assert len(sink.posts) == 1 and sink.posts[0]["json"]["id"] == cid and len(sink.posts[0]["json"]["claims"]) == 3
    shot(page, "console-sent.png")

    page.get_by_role("button", name="Audit").click()
    page.get_by_text("Chain intact").wait_for()
    assert page.locator("tbody tr").count() >= 10
    shot(page, "console-audit.png")
    assert page.console_errors == []


def test_release_copy_is_never_interpreted_as_markup(client, live_server, page):
    make(client, title='<img src=x onerror="window.__xss=1">Quarterly note',
         body='<script>window.__xss=1</script>Plain text here.\n<a href="javascript:window.__xss=1">click</a>')
    sign_in_with_key(page, live_server, EDITOR["X-API-Key"])
    page.locator(".queue li button").first.click()
    page.locator(".line.title").wait_for()
    assert page.evaluate("window.__xss") is None
    assert page.locator(".proof img, .proof script, .proof a").count() == 0
    assert '<img src=x onerror="window.__xss=1">Quarterly note' in page.locator(".line.title .txt").inner_text()
    resp = page.request.get(live_server + "/console")
    csp = resp.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "default-src 'none'" in csp and "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp
    assert page.request.get(live_server + "/console/../config.py").status == 404
    assert page.request.get(live_server + "/console/console.js").headers["x-content-type-options"] == "nosniff"


def test_actions_follow_the_signed_in_role(client, live_server, page):
    make(client, classification="investor", title="Investor update")
    sign_in_with_key(page, live_server, EDITOR["X-API-Key"])
    page.get_by_role("button", name="Investor update").click()
    page.get_by_text("Approving needs the approver role.").wait_for()
    assert page.get_by_role("button", name="Approve this version").is_disabled()
    page.get_by_role("button", name="Audit").click()
    page.get_by_text("The audit trail needs the auditor role.").wait_for()
    page.get_by_role("button", name="Sign out").click()
    page.get_by_label("Access key").fill("definitely-not-a-key")
    page.get_by_role("button", name="Sign in with an access key").click()
    page.get_by_text("That access key was not recognised.").wait_for()


def test_company_sign_in_and_approval_in_the_browser(client, live_server, page, sso_on, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", live_server)
    sso_on.user = {"sub": "u-9", "email": "clo@corp.example", "email_verified": True, "groups": ["growthos-approver", "growthos-auditor"]}
    cid = make(client, classification="investor", title="Investor update")["id"]
    page.goto(live_server + "/console")
    assert page.get_by_text("Access keys cannot approve releases here.").is_visible()
    page.get_by_role("link", name="Sign in with your company account").click()   # -> IdP -> /auth/callback -> /console
    page.get_by_text("clo@corp.example").wait_for()
    cookie = [c for c in page.context.cookies() if c["name"] == "growthos_session"][0]
    assert cookie["httpOnly"] is True and cookie["sameSite"] == "Lax"
    assert page.evaluate("document.cookie") == ""                                  # script cannot read the session
    page.get_by_role("button", name="Investor update").click()
    page.get_by_role("button", name="Approve this version").click()                # sends X-CSRF-Token
    page.get_by_text("Approved this version.").wait_for()
    approval = client.get(f"/v1/content/{cid}", headers=EDITOR).json()["approval"]
    assert approval["approved_by"] == "clo@corp.example" and approval["identity"] == "sso"
    shot(page, "console-sso.png")
    page.get_by_role("button", name="Sign out").click()
    page.get_by_role("link", name="Sign in with your company account").wait_for()
    assert [c for c in page.context.cookies() if c["name"] == "growthos_session"] == []
    assert page.console_errors == []


def test_console_fits_a_phone_without_sideways_scrolling(client, live_server, browser):
    make(client, classification="pr", title="Parinita launches GrowthOS with a deliberately long headline for small screens", body=COPY, claims=[])
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    sign_in_with_key(page, live_server, BOOT["X-API-Key"])
    page.locator(".queue li button").first.click()
    page.locator(".line.title").wait_for()
    assert page.evaluate("document.scrollingElement.scrollWidth <= window.innerWidth")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "console-phone.png"), full_page=True)
    ctx.close()


def test_drafting_campaign_brand_and_sources_in_console(client, live_server, page, monkeypatch):
    from app import model_runtime
    monkeypatch.setattr(model_runtime, 'configured', lambda: True)
    monkeypatch.setattr(model_runtime, 'generate_json', lambda *args: ({'title': 'Workshop invitation', 'body': 'Please join the writing workshop.', 'summary': 'Workshop notes'}, 'model'))
    sign_in_with_key(page, live_server, BOOT['X-API-Key'])
    page.get_by_role('button', name='Brand voice', exact=True).click()
    page.get_by_label('Brand name', exact=True).fill('Cedar Studio')
    page.get_by_label('Voice and writing rules').fill('Direct and warm.')
    page.get_by_role('button', name='Save brand voice').click()
    page.get_by_text('Brand voice saved for future drafts.').wait_for()
    page.get_by_role('button', name='Drafting studio', exact=True).click()
    page.get_by_label('What should this content achieve?').fill('Invite our team to an online writing workshop.')
    page.get_by_label('Facts and source material', exact=True).fill('Cedar Studio hosts an online writing workshop for team leads.')
    page.get_by_role('button', name='Create four-format campaign').click()
    page.get_by_text('In this campaign', exact=True).wait_for()
    page.get_by_text('Original brief and sources', exact=True).click()
    assert page.locator('.source-notes').inner_text() == 'Cedar Studio hosts an online writing workshop for team leads.'
    assert len(client.get('/v1/content', headers=EDITOR).json()) == 4
    assert page.console_errors == []


def test_destination_setup_starts_disabled(client, live_server, page):
    sign_in_with_key(page, live_server, BOOT['X-API-Key'])
    page.get_by_role('button', name='Destinations', exact=True).click()
    page.get_by_label('Destination name', exact=True).fill('Newsroom')
    page.get_by_label('Short identifier', exact=True).fill('newsroom')
    page.get_by_role('button', name='Save destination', exact=True).click()
    page.get_by_text('Destination saved, switched off.', exact=False).wait_for()
    result = client.get('/v1/feeds', headers=BOOT).json()
    assert len(result) == 1 and result[0]['enabled'] is False
    assert page.console_errors == []


def test_connector_setup_edit_and_readiness(client, live_server, page, monkeypatch):
    monkeypatch.delenv('GROWTHOS_SECRET_CONSOLE_SLACK', raising=False)
    sign_in_with_key(page, live_server, BOOT['X-API-Key'])
    page.get_by_role('button', name='Destinations', exact=True).click()
    page.locator('#dest-type').wait_for()
    assert page.locator('#dest-type option').count() == 42
    page.get_by_label('Destination type').select_option('slack')
    page.get_by_label('Destination name', exact=True).fill('Team updates')
    page.get_by_label('Short identifier', exact=True).fill('team-updates')
    page.get_by_label('channel *', exact=True).fill('C123')
    page.get_by_label('Access token variable *', exact=True).fill('GROWTHOS_SECRET_CONSOLE_SLACK')
    page.get_by_role('button', name='Save destination', exact=True).click()
    page.get_by_text('Destination saved, switched off.', exact=False).wait_for()
    assert page.get_by_role('button', name='Turn on', exact=True).is_disabled()
    page.get_by_role('button', name='Edit settings', exact=True).click()
    assert page.get_by_label('channel *', exact=True).input_value() == 'C123'
    page.get_by_label('channel *', exact=True).fill('C456')
    page.get_by_role('button', name='Save destination', exact=True).click()
    page.get_by_text('Destination settings updated.', exact=True).wait_for()
    assert client.get('/v1/feeds', headers=BOOT).json()[0]['config']['channel'] == 'C456'
    monkeypatch.setenv('GROWTHOS_SECRET_CONSOLE_SLACK', 'test-token')
    page.get_by_role('button', name='Check configuration', exact=True).click()
    page.get_by_text('Configuration readiness refreshed.', exact=False).wait_for()
    assert page.get_by_role('button', name='Turn on', exact=True).is_enabled()
    assert page.console_errors == []


def test_company_setup_and_encrypted_credential_entry(client, live_server, page, monkeypatch):
    from cryptography.fernet import Fernet
    from app.config import settings
    from app.netguard import secret_from_env
    monkeypatch.setattr(settings, "connector_encryption_key", Fernet.generate_key().decode())
    sign_in_with_key(page, live_server, BOOT['X-API-Key'])
    page.get_by_role('button', name='Company setup', exact=True).click()
    page.get_by_role('heading', name='Secure account storage', exact=True).wait_for()
    page.get_by_role('button', name='Manage account credentials', exact=True).click()
    page.get_by_label('Credential name', exact=True).fill('GROWTHOS_SECRET_UI_VAULT')
    page.get_by_label('Account token or secret', exact=True).fill('synthetic-ui-credential')
    page.get_by_role('button', name='Save credential', exact=True).click()
    page.get_by_text('Credential saved securely.', exact=False).wait_for()
    assert page.get_by_label('Account token or secret', exact=True).input_value() == ''
    assert 'synthetic-ui-credential' not in page.locator('body').inner_text()
    assert secret_from_env('GROWTHOS_SECRET_UI_VAULT') == 'synthetic-ui-credential'
    page.get_by_role('button', name='Disconnect', exact=True).click()
    page.get_by_text('Credential removed.', exact=False).wait_for()
    assert secret_from_env('GROWTHOS_SECRET_UI_VAULT') == ''
    assert page.console_errors == []
