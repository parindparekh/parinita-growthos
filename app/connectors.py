"""Operator connector catalogue. Configuration readiness is not live certification."""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .adapters import REGISTRY
from .config import settings
from .db import get_db
from .models import FeedEndpoint
from .netguard import DestinationBlocked, _env_refs, secret_from_env, validate_endpoint_config
from .security import authenticate, require_role


# One source for console setup and API inventory. A trailing ? marks an optional field.
# Complex provider settings remain available through the advanced JSON editor.
SPECS = [
    ("rss", "RSS newsroom", "Feeds", "", ""),
    ("atom", "Atom feed", "Feeds", "", ""),
    ("jsonfeed", "JSON feed", "Feeds", "", ""),
    ("podcast_rss", "Podcast RSS", "Podcast and voice", "", "Hosted audio is required for each episode."),
    ("webhook", "Webhook", "Integration", "bearer_token_env? signing_secret_env?", "Receiver must honour the delivery idempotency key."),
    ("rest_json", "REST JSON", "Integration", "bearer_token_env?", "Uses the governed release JSON contract."),
    ("smtp", "Email (SMTP)", "Messaging", "to", "Configure the SMTP relay on the server. Recipient consent remains an operator responsibility."),
    ("linkedin", "LinkedIn", "Social", "author_urn bearer_token_env api_version?", "Requires an authorised member or organisation and posting scope. Renew tokens outside GrowthOS."),
    ("x", "X", "Social", "bearer_token_env? consumer_key_env? consumer_secret_env? access_token_env? access_token_secret_env?", "Supply either an OAuth 2 user token or all four OAuth 1 fields."),
    ("mastodon", "Mastodon", "Social", "bearer_token_env", "Use your instance URL."),
    ("bluesky", "Bluesky", "Social", "identifier app_password_env", "Optional custom PDS URL; otherwise bsky.social."),
    ("reddit", "Reddit", "Social", "subreddit client_id client_secret_env refresh_token_env? username? password_env?", "Supply a refresh token, or username and password for an authorised script app."),
    ("facebook", "Facebook Pages", "Social", "page_id page_token_env", "Page posting only; requires pages_manage_posts."),
    ("instagram", "Instagram", "Social", "ig_user_id access_token_env", "Professional account and a public HTTPS image on the release are required."),
    ("threads", "Threads", "Social", "user_id access_token_env", "Text container followed by publish; account permission required."),
    ("pinterest", "Pinterest", "Social", "board_id bearer_token_env", "Requires pins:write and a public image on the release."),
    ("tiktok", "TikTok video / photos", "Social", "access_token_env", "Creates a 15-second vertical video for creator inbox review. Photo mode remains available in advanced settings."),
    ("tumblr", "Tumblr", "Social", "blog bearer_token_env", "Uses Neue Post Format."),
    ("lemmy", "Lemmy", "Social", "community_id username password_env", "Use your instance URL."),
    ("slack", "Slack", "Messaging", "channel bearer_token_env", "Invite the bot to the channel; chat:write scope required."),
    ("teams", "Microsoft Teams", "Messaging", "webhook_url_env", "Store the complete Workflows webhook URL in the named server secret."),
    ("discord", "Discord", "Messaging", "webhook_url_env", "Store the complete webhook URL in the named server secret. Mentions are disabled."),
    ("telegram", "Telegram", "Messaging", "chat_id bot_token_env", "The bot must have access to the chat."),
    ("whatsapp", "WhatsApp Business", "Messaging", "phone_number_id bearer_token_env recipients_env template language?", "Approved templates and opted-in recipients only; not WhatsApp Channels."),
    ("google_chat", "Google Chat", "Messaging", "webhook_url_env", "Store the complete space webhook URL as a server secret."),
    ("mattermost", "Mattermost", "Messaging", "webhook_url_env channel?", "Incoming webhook URL belongs in a server secret."),
    ("matrix", "Matrix", "Messaging", "room_id access_token_env", "Homeserver URL and !room:server room ID required."),
    ("zulip", "Zulip", "Messaging", "bot_email api_key_env stream topic?", "Use the realm URL and a bot account."),
    ("wordpress", "WordPress", "Publishing", "username app_password_env status?", "Application password; defaults to a draft during setup."),
    ("devto", "Dev.to", "Publishing", "api_key_env", "Creates a draft by default during setup."),
    ("ghost", "Ghost", "Publishing", "admin_key_env", "Use the site URL and a server secret containing the Admin API id:secret."),
    ("buttondown", "Buttondown", "Publishing", "api_key_env", "Creates a draft by default during setup."),
    ("mailchimp", "Mailchimp", "Publishing", "api_key_env list_id from_name reply_to", "Creates a campaign draft by default; sending needs a consented audience."),
    ("etsy", "Etsy", "Commerce", "shop_id keystring bearer_token_env", "Updates an announcement or an existing listing; does not create inventory."),
    ("shopify", "Shopify blog", "Commerce", "blog_id access_token_env api_version?", "Store URL and write_content scope. Existing adapter uses the legacy REST contract; verify account access."),
    ("google_business", "Google Business Profile", "Commerce", "account_id location_id bearer_token_env", "Requires business.manage and access to the location."),
    ("transistor", "Transistor", "Podcast and voice", "show_id api_key_env", "Hosted audio required; creates an episode draft by default during setup."),
    ("buzzsprout", "Buzzsprout", "Podcast and voice", "podcast_id api_token_env", "Hosted audio required; creates an episode draft by default during setup."),
    ("pr_wire", "PR wire", "Publishing", "to?", "Configure either your contracted wire API or its email desk in advanced settings."),
    ("mcp", "MCP server", "Integration", "tool bearer_token_env?", "Use an authorised Streamable HTTP server and map release fields to tool arguments."),
    ("vaak", "Parinita Vaak", "Podcast and voice", "twin_id bearer_token_env?", "Enrolled voice, consent and shared media storage are required. This renders audio without publishing it."),
]
URL_REQUIRED = {"webhook", "rest_json", "mastodon", "wordpress", "mcp", "vaak", "lemmy", "shopify", "ghost", "matrix", "zulip"}
FEEDS = {"rss", "atom", "jsonfeed", "podcast_rss"}


def needs_url(protocol, direction, config):
    return (protocol in URL_REQUIRED or (protocol == "pr_wire" and config.get("mode", "api") == "api")
            or (protocol in FEEDS and direction != "outbound"))


def catalogue():
    result = []
    for protocol, name, group, fields, note in SPECS:
        defaults = {}
        if protocol in {"devto", "ghost", "buttondown", "mailchimp", "shopify"}:
            defaults["draft"] = True
        if protocol == "tiktok":
            defaults["media_type"] = "video"
        if protocol == "wordpress":
            defaults["status"] = "draft"
        if protocol in {"transistor", "buzzsprout"}:
            defaults["publish"] = False
        if protocol == "pr_wire":
            defaults = {"mode": "email", "to": ""}
        if protocol == "mcp":
            defaults["argument_map"] = {"text": "body"}
        result.append({"protocol": protocol, "name": name, "group": group, "note": note,
                       "implemented": protocol in REGISTRY or protocol in FEEDS,
                       "verification": "contract_tests", "directions": ["outbound", "inbound", "bidirectional"] if protocol in FEEDS else ["outbound"],
                       "url_required": protocol in URL_REQUIRED, "defaults": defaults,
                       "fields": [{"key": f.rstrip("?"), "required": not f.endswith("?"),
                                   "secret_reference": f.rstrip("?").endswith("_env")} for f in fields.split()]})
    return result


def endpoint_readiness(endpoint):
    """No network, no publishing, no secret values in the response."""
    problems, refs = [], []
    try:
        cfg = json.loads(endpoint.config_json or "{}")
        validate_endpoint_config(endpoint.url, cfg, needs_url=needs_url(endpoint.protocol, endpoint.direction, cfg),
                                 protocol=endpoint.protocol, direction=endpoint.direction)
        for field, name in _env_refs(cfg):
            present = bool(secret_from_env(name))
            refs.append({"field": field, "name": name, "present": present})
            if not present:
                problems.append(f"Server secret {name} is missing.")
        if endpoint.protocol == "smtp" or (endpoint.protocol == "pr_wire" and cfg.get("mode") == "email"):
            if not settings.smtp_host or not settings.smtp_from:
                problems.append("SMTP_HOST and SMTP_FROM must be configured on the server.")
            if settings.smtp_username and not settings.smtp_password:
                problems.append("SMTP_PASSWORD is missing for the configured SMTP user.")
        if endpoint.protocol == "vaak" and not settings.media_dir:
            problems.append("MEDIA_DIR and shared media storage must be configured.")
    except (DestinationBlocked, TypeError, ValueError, AttributeError):
        problems.append("Stored connector configuration is invalid; edit and save its settings.")
    return {"endpoint_id": endpoint.id, "enabled": endpoint.enabled, "configuration_ready": not problems,
            "live_verified": False, "secret_references": refs, "problems": problems,
            "note": "Checks settings and secret presence only. Account permissions, token expiry and delivery require a controlled live acceptance test."}


router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


@router.get("", dependencies=[Depends(authenticate)])
def list_connectors():
    return catalogue()


@router.get("/readiness", dependencies=[Depends(require_role("admin"))])
def readiness(db: Session = Depends(get_db)):
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "endpoints": [endpoint_readiness(e) for e in db.query(FeedEndpoint).all()],
            "services": [
                {"name": "Denizen / text model", "configured": bool(settings.text_model_base_url and settings.text_model_name and settings.text_model_api_key)},
                {"name": "Witness / OIDC identity", "configured": bool(settings.oidc_issuer and settings.oidc_client_id and settings.session_secret)},
                {"name": "Chrysalis assurance", "configured": bool(settings.chrysalis_enabled and settings.chrysalis_anchor_url and settings.chrysalis_receipt_verify_key)},
                {"name": "Audio storage", "configured": bool(settings.media_dir)},
            ]}
