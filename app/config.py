"""Runtime configuration. Unsafe production configurations fail closed at startup."""
import json
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field

log = logging.getLogger("growthos.config")
# HTTP client info logs include full URLs; bot and webhook credentials can be in paths or queries.
logging.getLogger("httpx").setLevel(logging.WARNING)

WEAK_KEYS = {"", "change-me-now", "changeme", "test", "test-key", "secret", "password", "growthos"}
MIN_KEY_LENGTH = 24
ROLES = {"admin", "editor", "approver", "publisher", "auditor"}


class ConfigError(RuntimeError):
    pass


class Settings(BaseSettings):
    app_name: str = "Parinita GrowthOS"
    environment: str = "development"

    # --- identity -----------------------------------------------------------
    # API_KEY is the bootstrap admin credential. In production it cannot record
    # human approvals; approvals need a named key from API_KEYS with the
    # `approver` role, so an approval is attributable to a person.
    api_key: str = ""
    # API_KEYS="alice:approver:<key>,ci:editor|publisher:<key>,ops:admin|auditor:<key>"
    api_keys: str = ""
    # None -> enforced in production, relaxed elsewhere.
    require_four_eyes: bool | None = None

    # --- SSO (OpenID Connect). Set OIDC_ISSUER + OIDC_CLIENT_ID to enable. ---------------------
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""           # empty = public client (PKCE only)
    oidc_scopes: str = "openid profile email"
    oidc_audience: str = ""                # audience for API bearer tokens; defaults to the client id
    # "witness" applies the Parinita Witness profile (Keycloak-based identity plane): roles are read from the GrowthOS
    # client's roles and realm roles as well as groups, and the sign-in button says Witness. Still plain OIDC.
    identity_provider: str = ""
    # Claim(s) that carry groups or roles. Comma-separated; dotted paths allowed (realm_access.roles).
    oidc_role_claim: str = "groups"
    # Values with this prefix name a GrowthOS role directly: "growthos:approver" -> approver.
    oidc_role_prefix: str = ""
    oidc_name_claim: str = ""              # default: verified email, else preferred_username, else sub
    # JSON: IdP group/role value -> GrowthOS roles. Unmapped users can sign in but hold no role.
    oidc_role_map: str = ('{"growthos-admin":["admin"],"growthos-editor":["editor"],"growthos-approver":["approver"],'
                          '"growthos-publisher":["publisher"],"growthos-auditor":["auditor"]}')
    oidc_algorithms: str = "RS256,ES256,PS256,RS384,ES384,RS512"
    session_secret: str = ""               # signs the console session cookie; >= 32 chars
    session_ttl_seconds: int = 28800
    # None -> keys stay enabled. Set false to make SSO the only way in.
    api_keys_enabled: bool = True
    # None -> true whenever SSO is configured: approvals, revocations and sentence waivers need an IdP identity.
    approval_requires_sso: bool | None = None

    # --- storage ------------------------------------------------------------
    database_url: str = "sqlite:///./data/growthos.db"
    public_base_url: str = "http://localhost:8080"

    # --- feed fabric --------------------------------------------------------
    feed_poll_seconds: int = 300
    http_timeout_seconds: int = 20
    max_feed_bytes: int = 5_000_000
    max_feed_entries: int = 500
    push_max_attempts: int = 3
    push_backoff_seconds: float = 0.5
    # JSON {"linkedin": "https://...", ...}. Points a provider adapter at a sandbox/mock. Operator-only (env).
    provider_base_overrides: str = ""

    # --- egress policy ------------------------------------------------------
    allow_private_destinations: bool = False
    destination_allowlist: str = ""  # comma-separated host suffixes; empty = any public host

    # Host suffixes of *your own* internal services (Vaak, Tapestry, an internal MCP server) that may resolve to
    # private addresses. Everything else stays subject to the public-address rule.
    trusted_internal_hosts: str = ""
    # Directory where rendered audio (Vaak) is written and served from /media. Empty = audio rendering disabled.
    media_dir: str = ""

    # --- MCP server (GrowthOS as a tool provider for agents) -------------------------------------
    mcp_enabled: bool = True
    mcp_allowed_origins: str = ""  # extra browser origins allowed to call /mcp; PUBLIC_BASE_URL is always allowed

    # --- Chrysalis trust anchor ----------------------------------------------
    # GrowthOS keeps a local append-only audit chain for fast verification, while
    # Chrysalis is the external assurance anchor. The endpoint contract is configurable
    # so it can target the deployed Chrysalis v6 assurance API without hardcoding a route.
    chrysalis_enabled: bool = False
    chrysalis_anchor_url: str = ""
    chrysalis_bearer_token_env: str = "GROWTHOS_SECRET_CHRYSALIS_TOKEN"
    chrysalis_fail_closed_high_risk: bool = True
    chrysalis_fail_closed_all: bool = False
    chrysalis_anchor_interval_seconds: int = 3600
    # Receipt verification (v1.6.1). A receipt is only as good as what GrowthOS checks before trusting it:
    #  - require_receipt_digest: the receipt must echo the submitted payload digest (payload_hash / digest) and it must match.
    #  - receipt_verify_key: PEM public key (Ed25519 or ECDSA P-256) that must have signed the receipt. The signature is
    #    base64 in the receipt's `signature` field, over canonical JSON (sorted keys, no spaces) of the receipt minus
    #    `signature`. Empty = receipts are accepted on transport authentication (TLS + bearer) alone.
    chrysalis_require_receipt_digest: bool = False
    chrysalis_receipt_verify_key: str = ""
    chrysalis_receipt_signature_field: str = "signature"

    # --- AEO probes ---------------------------------------------------------
    # Editors may run licensed answer-engine probes against operator-approved URLs. The only process secrets a probe may
    # attach are those under this prefix, so a probe can never be pointed at an attacker host to exfiltrate provider,
    # messaging or Chrysalis tokens (those live under other GROWTHOS_SECRET_* names).
    aeo_probe_secret_prefix: str = "GROWTHOS_SECRET_AEO_"

    # --- gate policy --------------------------------------------------------
    # Classes (beyond the high-risk set) where uncovered numerics/quotes block instead of warn.
    gate_evidence_classes: str = "pr,social"
    strict_numeric: bool = False
    # Sentence accounting (policy 1.2): block | warn | off. Blocks only in evidence classes.
    gate_sentence_mode: str = "block"
    # Share of a sentence's content words that must appear in one supported claim to count as covered.
    gate_sentence_match: float = 0.6
    # Who may record "needs no evidence" on a sentence: approver | editor.
    gate_waiver_role: str = "approver"

    # --- surface ------------------------------------------------------------
    docs_enabled: bool | None = None  # None -> off in production
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 240
    public_feed_rate_limit_per_minute: int = 600
    # Per-source-address ceiling that applies on top of the per-credential limit. Credential guessing, or spraying
    # random keys to mint fresh buckets, is bounded by this instead of being invisible to the limiter.
    rate_limit_per_ip_per_minute: int = 600
    # Hard cap on tracked buckets (least-recently-seen evicted first): memory stays bounded under key spraying.
    rate_limit_max_buckets: int = 50000

    # --- optional model gateway --------------------------------------------
    # Reuse Denizen Blu's existing connection variables; explicit GrowthOS values win.
    text_model_base_url: str = Field(default="", validation_alias=AliasChoices("text_model_base_url", "BLU_API_BASE"))
    text_model_api_key: str = Field(default="", validation_alias=AliasChoices("text_model_api_key", "BLU_API_KEY"), repr=False)
    text_model_name: str = Field(default="", validation_alias=AliasChoices("text_model_name", "BLU_MODEL"))
    text_model_timeout_seconds: int = Field(default=90, ge=5, le=300)
    text_model_max_tokens: int = Field(default=4096, ge=256, le=16384)

    # --- smtp ---------------------------------------------------------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- derived -----------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def four_eyes(self) -> bool:
        return self.is_production if self.require_four_eyes is None else self.require_four_eyes

    @property
    def docs_on(self) -> bool:
        return (not self.is_production) if self.docs_enabled is None else self.docs_enabled

    @property
    def trusted_internal(self) -> list[str]:
        return [h.strip().lower().lstrip(".") for h in self.trusted_internal_hosts.split(",") if h.strip()]

    @property
    def sso_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id)

    @property
    def is_witness(self) -> bool:
        return self.identity_provider.strip().lower() == "witness"

    @property
    def client_roles_path(self) -> str:
        return f"resource_access.{self.oidc_client_id}.roles"

    @property
    def role_claim_paths(self) -> list[str]:
        paths = [c.strip() for c in self.oidc_role_claim.split(",") if c.strip()]
        if self.is_witness and paths == ["groups"]:  # left at the default: use the Witness / Keycloak layout
            paths = [self.client_roles_path, "realm_access.roles", "roles", "groups"]
        return paths

    @property
    def approvals_need_sso(self) -> bool:
        return self.sso_enabled if self.approval_requires_sso is None else self.approval_requires_sso

    @property
    def role_map(self) -> dict[str, list[str]]:
        try:
            m = json.loads(self.oidc_role_map or "{}")
        except ValueError as exc:
            raise ConfigError("OIDC_ROLE_MAP must be JSON") from exc
        if not isinstance(m, dict):
            raise ConfigError("OIDC_ROLE_MAP must be a JSON object")
        out = {}
        for group, roles in m.items():
            roles = [roles] if isinstance(roles, str) else list(roles)
            if set(roles) - ROLES:
                raise ConfigError(f"OIDC_ROLE_MAP maps '{group}' to unknown role(s): {sorted(set(roles) - ROLES)}")
            out[str(group)] = roles
        return out

    @property
    def provider_bases(self) -> dict[str, str]:
        try:
            m = json.loads(self.provider_base_overrides or "{}")
        except ValueError as exc:
            raise ConfigError("PROVIDER_BASE_OVERRIDES must be JSON") from exc
        return {str(k): str(v).rstrip("/") for k, v in m.items()} if isinstance(m, dict) else {}

    @property
    def evidence_classes(self) -> set[str]:
        return {c.strip() for c in self.gate_evidence_classes.split(",") if c.strip()}

    @property
    def allowlist(self) -> list[str]:
        return [h.strip().lower().lstrip(".") for h in self.destination_allowlist.split(",") if h.strip()]

    def parsed_keys(self) -> list[tuple[str, str, frozenset[str]]]:
        """Return [(key, principal_name, roles)]. Raises ConfigError on malformed entries."""
        out: list[tuple[str, str, frozenset[str]]] = []
        if not self.api_keys_enabled:
            return out
        if self.api_key:
            roles = {"admin"} if self.is_production else {"admin", "approver"}
            out.append((self.api_key, "bootstrap", frozenset(roles)))
        for raw in (e.strip() for e in self.api_keys.split(",")):
            if not raw:
                continue
            parts = raw.split(":", 2)
            if len(parts) != 3 or not all(parts):
                raise ConfigError("API_KEYS entries must look like name:role1|role2:key")
            name, role_s, key = parts
            roles = frozenset(r.strip() for r in role_s.split("|") if r.strip())
            if not roles or roles - ROLES:
                raise ConfigError(f"API_KEYS entry '{name}' has unknown role(s): {sorted(roles - ROLES)}")
            out.append((key, name, roles))
        return out

    def validate_runtime(self) -> None:
        keys = self.parsed_keys()
        if not keys and not self.sso_enabled:
            raise ConfigError("No API credentials configured. Set API_KEY and/or API_KEYS, or configure OIDC.")
        if self.chrysalis_enabled and not self.chrysalis_anchor_url:
            raise ConfigError("CHRYSALIS_ENABLED requires CHRYSALIS_ANCHOR_URL")
        if self.chrysalis_anchor_url and not self.chrysalis_anchor_url.startswith(("http://", "https://")):
            raise ConfigError("CHRYSALIS_ANCHOR_URL must be absolute http(s)")
        if self.is_production and self.chrysalis_anchor_url and not self.chrysalis_anchor_url.startswith("https://"):
            raise ConfigError("Refusing to start in production: CHRYSALIS_ANCHOR_URL must be https://")
        if self.is_production and self.chrysalis_enabled:
            if not self.chrysalis_require_receipt_digest or not self.chrysalis_receipt_verify_key:
                raise ConfigError("Production Chrysalis requires digest echo and a receipt verification key")
        if self.chrysalis_receipt_verify_key:
            from .chrysalis import load_verify_key  # local import: chrysalis imports settings
            load_verify_key(self.chrysalis_receipt_verify_key)  # raises ConfigError on an unusable key
        if not self.aeo_probe_secret_prefix.startswith("GROWTHOS_SECRET_"):
            raise ConfigError("AEO_PROBE_SECRET_PREFIX must start with GROWTHOS_SECRET_")
        if self.gate_sentence_mode not in {"block", "warn", "off"}:
            raise ConfigError("GATE_SENTENCE_MODE must be block, warn or off")
        if self.identity_provider.strip().lower() not in {"", "witness"}:
            raise ConfigError("IDENTITY_PROVIDER must be empty (any OIDC provider) or 'witness'")
        if self.gate_waiver_role not in {"approver", "editor"}:
            raise ConfigError("GATE_WAIVER_ROLE must be approver or editor")
        self.provider_bases  # noqa: B018 - validates JSON
        if self.sso_enabled:
            self.role_map  # noqa: B018 - validates JSON and role names
            if len(self.session_secret) < 32:
                raise ConfigError("SESSION_SECRET must be set (>= 32 characters) when OIDC is configured.")
            if self.is_production and not self.oidc_issuer.lower().startswith("https://"):
                raise ConfigError("Refusing to start in production: OIDC_ISSUER must be https://")
        if len({k for k, _, _ in keys}) != len(keys):
            raise ConfigError("Duplicate API key values; every principal needs its own key.")
        if len({n for _, n, _ in keys}) != len(keys):
            raise ConfigError("Duplicate principal names in API_KEYS.")
        weak = [n for k, n, _ in keys if k.lower() in WEAK_KEYS or len(k) < MIN_KEY_LENGTH]
        if self.is_production:
            if weak:
                raise ConfigError(f"Refusing to start in production: weak/default API key for {weak} "
                                  f"(minimum {MIN_KEY_LENGTH} characters, no defaults).")
            if not self.public_base_url.lower().startswith("https://"):
                raise ConfigError("Refusing to start in production: PUBLIC_BASE_URL must be https://")
            if not self.sso_enabled and not any("approver" in r for _, _, r in keys):
                log.warning("No principal has the 'approver' role: high-risk content can never be released.")
        elif weak:
            log.warning("Weak/default API key in use for %s. Acceptable for local development only.", weak)


settings = Settings()
