import re
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel as _PydanticModel, Field, field_validator, model_validator

ClaimType = Literal["fact", "quote", "forecast", "opinion", "internal"]
Classification = Literal["general", "pr", "social", "investor", "regulated", "legal", "health", "financial"]
Protocol = Literal["rss", "atom", "jsonfeed", "podcast_rss", "webhook", "rest_json", "smtp",
                   "linkedin", "x", "mastodon", "bluesky", "transistor", "buzzsprout", "pr_wire",
                   "slack", "teams", "discord", "telegram", "whatsapp", "wordpress", "mcp", "vaak",
                   "reddit", "facebook", "instagram", "threads", "pinterest", "tiktok", "tumblr", "lemmy", "etsy", "shopify", "google_business", "devto", "ghost", "buttondown", "mailchimp", "google_chat", "mattermost", "matrix", "zulip"]
Disposition = Literal["opinion", "boilerplate", "not_factual"]

# A source must be a resolvable reference, not a free-text token.
SOURCE_SCHEMES = {"https", "http", "doi", "urn", "internal", "chrysalis", "s3", "gs"}
_URI = re.compile(r"^([a-z][a-z0-9+.\-]*):(//)?\S{3,}$", re.I)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,198}[a-z0-9]$|^[a-z0-9]$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}$")


def _strip_nul(v):
    if isinstance(v, str):
        return v.replace("\x00", "")
    if isinstance(v, dict):
        return {k: _strip_nul(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_strip_nul(x) for x in v]
    return v


class BaseModel(_PydanticModel):
    """All request models drop NUL bytes: PostgreSQL text columns reject them (a 500 in v1.0)."""

    @model_validator(mode="before")
    @classmethod
    def _no_nul(cls, data):
        return _strip_nul(data)


def valid_source_uri(uri: str) -> bool:
    m = _URI.match(uri or "")
    return bool(m and m.group(1).lower() in SOURCE_SCHEMES)


def _check_web_url(v: str) -> str:
    if v and not re.match(r"^https?://[^\s/]+", v, re.I):
        raise ValueError("must be an absolute http(s) URL")
    return v


def _check_id(v: str | None) -> str | None:
    if v is not None and not _ID.match(v):
        raise ValueError("id must be 1-64 chars of [A-Za-z0-9._:-]")
    return v


def _check_content_metadata(value):
    # These fields are produced by authenticated server workflows, not by caller assertions.
    if value is not None and {"agent_history", "vaak", "editorial_review"} & value.keys():
        raise ValueError("agent_history, vaak and editorial_review are server-managed metadata")
    return value


class SourceRef(BaseModel):
    uri: str
    title: str = ""
    source_type: str = "web"
    published_at: str | None = None

    @field_validator("uri")
    @classmethod
    def _uri(cls, v):
        if not valid_source_uri(v):
            raise ValueError(f"source uri must use one of {sorted(SOURCE_SCHEMES)} (e.g. https://..., internal://memo-12)")
        return v


class Claim(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    claim_type: ClaimType = "fact"
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    # Sentence hashes (from GET /v1/content/{id}/assertions) this claim is evidence for.
    covers: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("covers")
    @classmethod
    def _covers(cls, v):
        for h in v:
            if not re.fullmatch(r"[0-9a-f]{16}", h):
                raise ValueError("covers entries must be 16-character sentence hashes")
        return v


class ContentCreate(BaseModel):
    id: str | None = None
    campaign_id: str | None = None
    content_type: str = Field(default="article", max_length=50)
    title: str = Field(max_length=500)
    body: str
    summary: str = ""
    locale: str = Field(default="en-US", max_length=20)
    source: str = Field(default="", max_length=1000)
    classification: Classification = "general"
    cta_url: str = Field(default="", max_length=2000)
    claims: list[Claim] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))
    _v_cta = field_validator("cta_url")(classmethod(lambda cls, v: _check_web_url(v)))
    _v_metadata = field_validator("metadata")(classmethod(lambda cls, v: _check_content_metadata(v)))


class ContentUpdate(BaseModel):
    """Partial update. Any change to a governed field invalidates approval and returns the item to draft."""
    campaign_id: str | None = None
    content_type: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=500)
    body: str | None = None
    summary: str | None = None
    locale: str | None = Field(default=None, max_length=20)
    source: str | None = Field(default=None, max_length=1000)
    classification: Classification | None = None
    cta_url: str | None = Field(default=None, max_length=2000)
    claims: list[Claim] | None = None
    metadata: dict[str, Any] | None = None

    _v_cta = field_validator("cta_url")(classmethod(lambda cls, v: _check_web_url(v) if v else v))
    _v_metadata = field_validator("metadata")(classmethod(lambda cls, v: _check_content_metadata(v)))


class FeedEndpointCreate(BaseModel):
    id: str | None = None
    name: str = Field(max_length=200)
    slug: str
    direction: Literal["inbound", "outbound", "bidirectional"]
    protocol: Protocol
    url: str = Field(default="", max_length=2000)
    channel: str = Field(default="generic", max_length=50)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    poll_seconds: int = Field(default=300, ge=60, le=86400)

    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))

    @field_validator("slug")
    @classmethod
    def _slug(cls, v):
        if not _SLUG.match(v):
            raise ValueError("slug must be lowercase letters, digits, '-' or '_'")
        return v


class FeedEndpointUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    channel: str | None = Field(default=None, max_length=50)
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    poll_seconds: int | None = Field(default=None, ge=60, le=86400)


class CampaignCreate(BaseModel):
    id: str | None = None
    name: str = Field(max_length=300)
    objective: str = ""
    audiences: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    default_cta_url: str = Field(default="", max_length=2000)

    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))
    _v_cta = field_validator("default_cta_url")(classmethod(lambda cls, v: _check_web_url(v)))


class ApprovalRequest(BaseModel):
    # Free-text attestation only (e.g. the reviewer's legal name). The accountable identity
    # is the principal bound to the API key and is recorded as approved_by.
    approver: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=2000)


class DispositionRequest(BaseModel):
    """A reviewer's decision that a sentence needs no evidence. Bound to the sentence hash."""
    disposition: Disposition
    note: str = Field(default="", max_length=500)


class PublishRequest(BaseModel):
    endpoint_id: str


class AgentRunRequest(BaseModel):
    agent: Literal["signal", "pr", "media", "podcast", "social", "amplify", "engagement", "acquire", "claim", "aeo", "performance", "gate", "rally",
                   "reddit", "facebook", "instagram", "threads", "pinterest", "tiktok", "tumblr", "etsy", "shopify", "local", "blog", "newsletter",
                   "community", "channels"]
    options: dict[str, Any] = Field(default_factory=dict)

class ScheduleCreate(BaseModel):
    endpoint_id: str
    run_at: datetime


class PerformanceEventCreate(BaseModel):
    id: str | None = None
    content_id: str | None = None
    endpoint_id: str | None = None
    channel: str = Field(default="", max_length=50)
    metric: Literal["impressions", "views", "reach", "engagements", "likes", "comments", "shares", "clicks", "conversions", "watch_seconds", "downloads", "mentions", "citations"]
    value: float = Field(ge=0)
    source: str = Field(default="manual", max_length=100)
    period_start: datetime | None = None
    period_end: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))


class InboxMessageCreate(BaseModel):
    id: str | None = None
    provider: str = Field(max_length=50)
    endpoint_id: str | None = None
    thread_id: str = Field(default="", max_length=200)
    external_id: str = Field(max_length=300)
    sender: str = Field(default="", max_length=300)
    body: str = Field(min_length=1)
    locale: str = Field(default="en-US", max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime | None = None

    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))


class InboxStateUpdate(BaseModel):
    state: Literal["new", "triaged", "responded", "dismissed"]


class AEOQueryCreate(BaseModel):
    id: str | None = None
    name: str = Field(max_length=300)
    prompt: str = Field(min_length=1)
    brand: str = Field(default="Parinita", max_length=200)
    engines: list[str] = Field(default_factory=lambda: ["manual"], max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=50)
    active: bool = True

    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))


class AEOProbeCreate(BaseModel):
    id: str | None = None
    query_id: str | None = None
    engine: str = Field(max_length=50)
    prompt: str = ""
    brand: str = Field(default="Parinita", max_length=200)
    response_text: str = ""
    citations: list[str] = Field(default_factory=list, max_length=100)
    brand_mentioned: bool | None = None
    source: str = Field(default="manual", max_length=100)

    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))

class ClaimConfirmRequest(BaseModel):
    candidate_id: str = Field(min_length=8, max_length=64)
    claim_type: ClaimType
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ClaimAddRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    claim_type: ClaimType
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)

class AEOProbeRun(BaseModel):
    query_id: str | None = None
    engine: str = Field(max_length=50)
    url: str = Field(max_length=2000)
    prompt: str = ""
    brand: str = Field(default="Parinita", max_length=200)
    bearer_token_env: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    request_body: dict[str, Any] = Field(default_factory=dict)
    prompt_field: str = Field(default="prompt", max_length=100)
    answer_path: str = Field(default="answer", max_length=200)
    citations_path: str = Field(default="citations", max_length=200)

    _v_url = field_validator("url")(classmethod(lambda cls, v: _check_web_url(v)))


class MediaContactCreate(BaseModel):
    id: str | None = None
    provider: str = Field(max_length=50)
    external_id: str = Field(max_length=300)
    name: str = Field(min_length=1, max_length=300)
    outlet: str = Field(default="", max_length=300)
    beat: str = Field(default="", max_length=500)
    email: str = Field(default="", max_length=500)
    profile_url: str = Field(default="", max_length=2000)
    location: str = Field(default="", max_length=300)
    influence_score: float = Field(default=0, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))


class MediaCoverageCreate(BaseModel):
    id: str | None = None
    provider: str = Field(max_length=50)
    external_id: str = Field(max_length=300)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(default="", max_length=2000)
    outlet: str = Field(default="", max_length=300)
    author: str = Field(default="", max_length=300)
    body: str = ""
    topics: list[str] = Field(default_factory=list, max_length=100)
    sentiment: Literal["positive", "neutral", "negative", "mixed", "unknown"] = "unknown"
    content_id: str | None = None
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))
    _v_url = field_validator("url")(classmethod(lambda cls, v: _check_web_url(v) if v else v))


class OpportunityStateUpdate(BaseModel):
    status: Literal["new", "reviewed", "accepted", "dismissed"]


class ClaimObservationCreate(BaseModel):
    id: str | None = None
    sentence_hash: str = Field(default="", max_length=32)
    claim_text: str = Field(min_length=1, max_length=3000)
    observation_type: Literal["earned-media", "aeo-citation", "social-reuse", "provider-observation"]
    provider: str = Field(default="", max_length=100)
    uri: str = Field(default="", max_length=2000)
    observed_text: str = ""
    matched_score: float = Field(default=0, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    _v_id = field_validator("id")(classmethod(lambda cls, v: _check_id(v)))
