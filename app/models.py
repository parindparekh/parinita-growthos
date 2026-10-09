from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(timezone.utc)


class BrandProfile(Base):
    __tablename__ = "brand_profiles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_json: Mapped[str] = mapped_column(Text, default="{}")


class ContentItem(Base):
    __tablename__ = "content_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    content_type: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    locale: Mapped[str] = mapped_column(String(20), default="en-US")
    source: Mapped[str] = mapped_column(String(1000), default="")
    # draft -> approved | blocked -> published. Any governed edit returns the item to draft.
    state: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    classification: Mapped[str] = mapped_column(String(30), default="general", index=True)
    cta_url: Mapped[str] = mapped_column(String(2000), default="")
    claims_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    approval_json: Mapped[str] = mapped_column(Text, default="{}")
    # Reviewer decisions on individual sentences, keyed by sentence hash (see gate.account).
    dispositions_json: Mapped[str] = mapped_column(Text, default="{}")
    # SHA-256 over the governed fields only (see content.governed_hash). Approvals bind to it.
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    updated_by: Mapped[str] = mapped_column(String(100), default="")  # last principal to change a governed field
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class FeedEndpoint(Base):
    __tablename__ = "feed_endpoints"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(20), index=True)  # inbound/outbound/bidirectional
    protocol: Mapped[str] = mapped_column(String(30))  # rss/atom/jsonfeed/podcast_rss/webhook/rest_json/smtp
    url: Mapped[str] = mapped_column(String(2000), default="")
    channel: Mapped[str] = mapped_column(String(50), default="generic")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    poll_seconds: Mapped[int] = mapped_column(Integer, default=300)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(30), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    objective: Mapped[str] = mapped_column(Text, default="")
    audiences_json: Mapped[str] = mapped_column(Text, default="[]")
    channels_json: Mapped[str] = mapped_column(Text, default="[]")
    default_cta_url: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Delivery(Base):
    """One row per (content version, destination). Makes publishing idempotent and observable."""
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("content_id", "endpoint_id", "content_hash", name="uq_delivery_version_dest"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # also the Idempotency-Key sent downstream
    content_id: Mapped[str] = mapped_column(String(64), index=True)
    endpoint_id: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/sent/failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_id: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    # prev_hash is unique: the chain cannot fork even if two writers race.
    __table_args__ = (UniqueConstraint("prev_hash", name="uq_audit_prev_hash"),)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    content_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(30), default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")  # canonical JSON, exactly as hashed
    event_hash: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    ts: Mapped[str] = mapped_column(String(40), default="")  # ISO-8601 UTC, covered by the hash
    hash_version: Mapped[int] = mapped_column(Integer, default=2)  # 1 = v1.0 legacy rows
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ScheduledDelivery(Base):
    """A governed future publish. The worker re-checks Gate and destination policy at send time."""
    __tablename__ = "scheduled_deliveries"
    __table_args__ = (UniqueConstraint("content_id", "endpoint_id", "content_hash", "run_at", name="uq_schedule_version_dest_time"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_id: Mapped[str] = mapped_column(String(64), index=True)
    endpoint_id: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)  # scheduled/sent/failed/cancelled/stale
    delivery_id: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class PerformanceEvent(Base):
    """Normalized outcome metric from a destination, analytics system, or conversion webhook."""
    __tablename__ = "performance_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    endpoint_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    channel: Mapped[str] = mapped_column(String(50), default="", index=True)
    metric: Mapped[str] = mapped_column(String(50), index=True)  # impressions/views/clicks/engagements/conversions/etc.
    value: Mapped[str] = mapped_column(String(64), default="0")  # decimal-as-string avoids cross-db float drift
    source: Mapped[str] = mapped_column(String(100), default="manual")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class InboxMessage(Base):
    """Normalized inbound/community message. Provider webhooks can map into this envelope."""
    __tablename__ = "inbox_messages"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_inbox_provider_external"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    endpoint_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    thread_id: Mapped[str] = mapped_column(String(200), default="", index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    sender: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(20), default="en-US")
    state: Mapped[str] = mapped_column(String(30), default="new", index=True)  # new/triaged/responded/dismissed
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    intent: Mapped[str] = mapped_column(String(50), default="unknown")
    response_draft: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AEOQuery(Base):
    """A prompt/query GrowthOS tracks across answer engines."""
    __tablename__ = "aeo_queries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    prompt: Mapped[str] = mapped_column(Text)
    brand: Mapped[str] = mapped_column(String(200), default="Parinita", index=True)
    engines_json: Mapped[str] = mapped_column(Text, default='["manual"]')
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AEOProbe(Base):
    """One observed answer-engine response and its citations. Can be entered by a live adapter or operator."""
    __tablename__ = "aeo_probes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    query_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    engine: Mapped[str] = mapped_column(String(50), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    brand: Mapped[str] = mapped_column(String(200), default="Parinita", index=True)
    response_text: Mapped[str] = mapped_column(Text, default="")
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source: Mapped[str] = mapped_column(String(100), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class MediaContact(Base):
    """Normalized journalist/analyst/creator contact imported from a licensed provider or internal directory."""
    __tablename__ = "media_contacts"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_media_contact_provider_external"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    name: Mapped[str] = mapped_column(String(300), index=True)
    outlet: Mapped[str] = mapped_column(String(300), default="", index=True)
    beat: Mapped[str] = mapped_column(String(500), default="")
    email: Mapped[str] = mapped_column(String(500), default="")
    profile_url: Mapped[str] = mapped_column(String(2000), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    influence_score: Mapped[str] = mapped_column(String(64), default="0")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MediaCoverage(Base):
    """Normalized earned-media/analyst/creator coverage observation."""
    __tablename__ = "media_coverage"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_media_coverage_provider_external"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    external_id: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(2000), default="", index=True)
    outlet: Mapped[str] = mapped_column(String(300), default="", index=True)
    author: Mapped[str] = mapped_column(String(300), default="", index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    topics_json: Mapped[str] = mapped_column(Text, default="[]")
    sentiment: Mapped[str] = mapped_column(String(30), default="unknown")
    content_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Opportunity(Base):
    """A ranked communications opportunity produced from observed signals, not an approval to publish."""
    __tablename__ = "opportunities"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_opportunity_fingerprint"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[str] = mapped_column(String(64), default="0", index=True)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    source_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    recommendation_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by_agent: Mapped[str] = mapped_column(String(100), default="Parinita Signal Agent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ClaimObservation(Base):
    """Observed downstream use of an approved claim (earned media, AEO citation, social reuse, etc.)."""
    __tablename__ = "claim_observations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_id: Mapped[str] = mapped_column(String(64), index=True)
    sentence_hash: Mapped[str] = mapped_column(String(32), default="", index=True)
    claim_text: Mapped[str] = mapped_column(Text)
    observation_type: Mapped[str] = mapped_column(String(50), index=True)
    provider: Mapped[str] = mapped_column(String(100), default="")
    uri: Mapped[str] = mapped_column(String(2000), default="", index=True)
    observed_text: Mapped[str] = mapped_column(Text, default="")
    matched_score: Mapped[str] = mapped_column(String(64), default="0")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class ChrysalisAnchor(Base):
    """Receipt binding a GrowthOS audit head or governed release version to Chrysalis."""
    __tablename__ = "chrysalis_anchors"
    __table_args__ = (UniqueConstraint("anchor_type", "content_id", "content_hash", "audit_head_hash", name="uq_chrysalis_anchor_subject"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    anchor_type: Mapped[str] = mapped_column(String(30), index=True)  # audit_head / release
    content_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    audit_head_hash: Mapped[str] = mapped_column(String(64), default="")
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    chrysalis_ref: Mapped[str] = mapped_column(String(300), default="", index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    receipt_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    anchored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
