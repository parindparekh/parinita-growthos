"""Destination adapter contract.

An adapter only maps and transports. It never decides whether content may be released:
feed_fabric.push_content() runs the destination policy, the Hallucination Gate, idempotency
and audit *around* every adapter, so a provider adapter cannot bypass them.

Built in:  webhook / rest_json, smtp,
           linkedin, x, mastodon, bluesky         (social)
           transistor, buzzsprout                 (podcast hosts)
           pr_wire                                (wire desk by email, or a contracted wire API by field map)
           slack, teams, discord, telegram        (team and community messaging)
           whatsapp                               (approved template messages via the WhatsApp Cloud API)
           wordpress                              (newsroom / CMS)
           mcp                                    (call a tool on any remote MCP server)
           vaak                                   (render the approved copy as governed audio through Parinita Vaak)
           reddit, facebook, instagram, threads, pinterest, tiktok, tumblr, lemmy      (v1.7 social)
           etsy, shopify, google_business                                              (v1.7 commerce / local)
           devto, ghost, buttondown, mailchimp                                         (v1.7 blogs / newsletters)
           google_chat, mattermost, matrix, zulip                                      (v1.7 messaging)

To add a provider: subclass Adapter, call register(), add the protocol to schemas.Protocol.
See docs/PROVIDER_ADAPTER_GUIDE.md.
"""
from dataclasses import dataclass


@dataclass
class DeliveryResult:
    ok: bool
    status_code: int | None = None
    provider_id: str = ""
    detail: str = ""
    attempts: int = 1
    # False for adapters that produce something from the release (e.g. rendered audio) rather than release it.
    publishes: bool = True
    # Non-governed metadata to attach to the content item (allow-listed keys only; see feed_fabric.ARTIFACT_KEYS).
    artifacts: dict | None = None


class Adapter:
    protocols: set[str] = set()

    def check_config(self, url: str, cfg: dict) -> str:
        """Return a human-readable problem with the endpoint config, or '' if it is usable."""
        return ""

    def send(self, payload: dict, endpoint, cfg: dict, idempotency_key: str, resume: str = "") -> DeliveryResult:  # pragma: no cover
        """`resume` is the provider_id recorded by a previous failed attempt of this same delivery,
        so multi-step providers can continue instead of creating a duplicate."""
        raise NotImplementedError


REGISTRY: dict[str, Adapter] = {}


def register(adapter: Adapter) -> None:
    for p in adapter.protocols:
        REGISTRY[p] = adapter


from . import webhook, smtp, social, podcast, pr_wire, messaging, whatsapp, cms, mcp_client, vaak  # noqa: E402,F401  (self-registering built-ins)
from . import reddit, meta, social_more, commerce, publishing, messaging_more  # noqa: E402,F401  (v1.7 destinations)

from . import ai_studio  # noqa: E402,F401
