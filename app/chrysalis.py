"""Chrysalis anchoring for GrowthOS audit heads and governed release attestations."""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .audit import record_event, verify_chain
from .config import ConfigError, settings
from .gate import HIGH_RISK, dispositions_hash, evaluate
from .models import ChrysalisAnchor, ContentItem
from .netguard import safe_post, secret_from_env

RECEIPT_PROFILE = "parinita.chrysalis.receipt-signature.v1"


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


# ----------------------------------------------------------------------------- receipt verification
def load_verify_key(pem: str):
    """Ed25519 or ECDSA P-256 public key in PEM. Anything else is a configuration error, not a runtime surprise."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    try:
        key = serialization.load_pem_public_key(pem.replace("\\n", "\n").encode())
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"CHRYSALIS_RECEIPT_VERIFY_KEY is not a readable PEM public key: {type(exc).__name__}") from exc
    if isinstance(key, ed25519.Ed25519PublicKey):
        return key
    if isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1):
        return key
    raise ConfigError("CHRYSALIS_RECEIPT_VERIFY_KEY must be an Ed25519 or ECDSA P-256 public key")


def verify_receipt(receipt: dict, payload_hash: str) -> dict:
    """Checks a Chrysalis receipt before GrowthOS records it as proof. Raises RuntimeError on any failure.

    1. The receipt names an anchor/reference id.
    2. If it echoes a digest, the digest equals the submitted payload hash; when CHRYSALIS_REQUIRE_RECEIPT_DIGEST
       is on the echo is mandatory.
    3. If CHRYSALIS_RECEIPT_VERIFY_KEY is set, the receipt carries a valid signature from that key over the canonical
       JSON of every field except the signature itself (profile parinita.chrysalis.receipt-signature.v1).
    Returns {"ref": ..., "digest_verified": bool, "signature_verified": bool}."""
    if not isinstance(receipt, dict):
        raise RuntimeError("Chrysalis receipt must be a JSON object")
    ref = _receipt_ref(receipt)
    if not ref:
        raise RuntimeError("Chrysalis receipt did not include an anchor/reference id")
    returned_hash = str(receipt.get("payload_hash") or receipt.get("digest") or "")
    if settings.chrysalis_require_receipt_digest and not returned_hash:
        raise RuntimeError("Chrysalis receipt did not echo the payload digest (CHRYSALIS_REQUIRE_RECEIPT_DIGEST)")
    if returned_hash and returned_hash.lower() != payload_hash:
        raise RuntimeError("Chrysalis receipt digest does not match submitted payload")
    if settings.is_production and settings.chrysalis_enabled and (not returned_hash or not settings.chrysalis_receipt_verify_key):
        raise RuntimeError("Production Chrysalis requires a signed, digest-bound receipt")
    signature_verified = False
    if settings.chrysalis_receipt_verify_key:
        field = settings.chrysalis_receipt_signature_field or "signature"
        sig_b64 = receipt.get(field)
        if not isinstance(sig_b64, str) or not sig_b64:
            raise RuntimeError("Chrysalis receipt is not signed but a verification key is configured")
        try:
            sig = base64.b64decode(sig_b64 + "=" * (-len(sig_b64) % 4), validate=True)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Chrysalis receipt signature is not base64") from exc
        body = _canonical({k: v for k, v in receipt.items() if k != field})
        key = load_verify_key(settings.chrysalis_receipt_verify_key)
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, ed25519
        try:
            if isinstance(key, ed25519.Ed25519PublicKey):
                key.verify(sig, body)
            else:
                key.verify(sig, body, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise RuntimeError("Chrysalis receipt signature does not verify against the configured key") from exc
        signature_verified = True
    return {"ref": ref, "digest_verified": bool(returned_hash), "signature_verified": signature_verified}


def _post(payload: dict, idempotency_key: str) -> dict:
    if not settings.chrysalis_anchor_url:
        raise RuntimeError("CHRYSALIS_ANCHOR_URL is not configured")
    headers = {"Content-Type": "application/json", "Idempotency-Key": idempotency_key}
    env = settings.chrysalis_bearer_token_env
    if env:
        token = secret_from_env(env)
        if not token:
            raise RuntimeError(f"Chrysalis secret {env} is not set")
        headers["Authorization"] = "Bearer " + token
    r = safe_post(settings.chrysalis_anchor_url, content=_canonical(payload), headers=headers, max_bytes=1_000_000)
    r.raise_for_status()
    try:
        receipt = r.json()
    except ValueError as exc:
        raise RuntimeError("Chrysalis anchor endpoint returned non-JSON receipt") from exc
    if not isinstance(receipt, dict):
        raise RuntimeError("Chrysalis anchor receipt must be a JSON object")
    return receipt


def _receipt_ref(receipt: dict) -> str:
    value = receipt.get("anchor_id") or receipt.get("receipt_id") or receipt.get("reference") or receipt.get("id")
    return value if isinstance(value, str) and value.strip() else ""


def _anchor(db: Session, *, anchor_type: str, payload: dict, content_id: str | None = None,
            content_hash: str = "", audit_head_hash: str = "", actor: str = "system", commit: bool = True) -> ChrysalisAnchor:
    """Submit one anchor. With commit=False the caller owns the transaction (publish keeps its row lock and commits the
    anchor together with the delivery claim), otherwise the outcome is committed here so a failure is never lost."""
    raw = _canonical(payload); payload_hash = hashlib.sha256(raw).hexdigest()
    existing = db.query(ChrysalisAnchor).filter(ChrysalisAnchor.anchor_type == anchor_type,
                                                 ChrysalisAnchor.content_id == content_id,
                                                 ChrysalisAnchor.content_hash == content_hash,
                                                 ChrysalisAnchor.audit_head_hash == audit_head_hash).first()
    if existing and existing.status == "anchored" and anchor_type != "release":
        return existing
    row = existing or ChrysalisAnchor(id=str(uuid.uuid4()), anchor_type=anchor_type, content_id=content_id,
                                      content_hash=content_hash, audit_head_hash=audit_head_hash, payload_hash=payload_hash)
    row.payload_hash = payload_hash; row.status = "pending"; row.error = ""
    db.add(row); db.flush()
    try:
        receipt = _post(payload, row.id)
        checked = verify_receipt(receipt, payload_hash)
        receipt["_growthos_verification"] = {"profile": RECEIPT_PROFILE, "digest_verified": checked["digest_verified"],
                                             "signature_verified": checked["signature_verified"]}
        if anchor_type == "release":
            receipt["_growthos_release_binding"] = _release_binding(payload["release"], payload["approval"], payload["dispositions_hash"])
        row.status = "anchored"; row.chrysalis_ref = checked["ref"]; row.receipt_json = json.dumps(receipt, ensure_ascii=False)
        row.anchored_at = datetime.now(timezone.utc); row.error = ""
        decision = "anchored"
    except Exception as exc:
        row.status = "failed"; row.error = f"{type(exc).__name__}: {exc}"[:1000]
        row.receipt_json = "{}"; decision = "failed"
    db.add(row)
    record_event(db, content_id=content_id, actor=f"Chrysalis Anchor (run by {actor})", action=f"chrysalis.{anchor_type}",
                 decision=decision, details={"anchor_id": row.id, "payload_hash": payload_hash,
                                             "chrysalis_ref": row.chrysalis_ref, "error": row.error})
    if commit:
        db.commit()
    else:
        db.flush()
    return row


def anchor_audit_head(db: Session, actor: str = "system") -> ChrysalisAnchor:
    v = verify_chain(db)
    if not v.get("ok"):
        raise RuntimeError("GrowthOS audit chain verification failed; refusing Chrysalis anchor")
    payload = {"schema": "parinita.growthos.chrysalis.audit-head.v1", "product": "Parinita GrowthOS",
               "audit": {"head_hash": v.get("head_hash", ""), "events": v.get("events", 0), "verified": True},
               "observed_at": datetime.now(timezone.utc).isoformat()}
    return _anchor(db, anchor_type="audit_head", payload=payload, audit_head_hash=str(v.get("head_hash") or ""), actor=actor)


def _release_binding(release: dict, approval: dict, dispositions: str) -> str:
    # State may move approved -> published; authority/evidence binding must not.
    fields = {k: release.get(k) for k in ("content_id", "content_hash", "classification")}
    return hashlib.sha256(_canonical({"release": fields, "approval": approval, "dispositions_hash": dispositions})).hexdigest()


def anchor_release(db: Session, item: ContentItem, actor: str = "system", commit: bool = True) -> ChrysalisAnchor:
    g = evaluate(item)
    if not g.passed:
        raise RuntimeError("Gate must pass before a release can be attested in Chrysalis")
    binding = _release_binding({"content_id": item.id, "content_hash": item.content_hash, "classification": item.classification},
                               json.loads(item.approval_json or "{}"), dispositions_hash(item))
    existing = (db.query(ChrysalisAnchor).filter(ChrysalisAnchor.anchor_type == "release",
                                                 ChrysalisAnchor.content_id == item.id,
                                                 ChrysalisAnchor.content_hash == item.content_hash,
                                                 ChrysalisAnchor.status == "anchored")
                .order_by(ChrysalisAnchor.anchored_at.desc()).first())
    if existing:
        try:
            receipt = json.loads(existing.receipt_json or "{}")
        except ValueError:
            receipt = {}
        if receipt.get("_growthos_release_binding") == binding:
            # Verify using the current trust key/policy; rotation cannot reuse old assurance.
            clean = {k: v for k, v in receipt.items() if not k.startswith("_growthos_")}
            try:
                verify_receipt(clean, existing.payload_hash)
            except (RuntimeError, ConfigError):
                pass
            else:
                return existing
    v = verify_chain(db)
    if not v.get("ok"):
        raise RuntimeError("GrowthOS audit chain verification failed; refusing release attestation")
    payload = {"schema": "parinita.growthos.chrysalis.release.v1", "product": "Parinita GrowthOS",
               "release": {"content_id": item.id, "content_hash": item.content_hash, "title": item.title,
                           "classification": item.classification, "state": item.state},
               "approval": json.loads(item.approval_json or "{}"),
               "dispositions_hash": dispositions_hash(item),
               "gate": {"passed": g.passed, "checks": g.checks},
               "audit_head_hash": v.get("head_hash", ""), "observed_at": datetime.now(timezone.utc).isoformat()}
    return _anchor(db, anchor_type="release", payload=payload, content_id=item.id, content_hash=item.content_hash,
                   audit_head_hash=str(v.get("head_hash") or ""), actor=actor, commit=commit)


def ensure_before_publish(db: Session, item: ContentItem, actor: str) -> ChrysalisAnchor | None:
    if not settings.chrysalis_enabled:
        return None
    row = anchor_release(db, item, actor=actor, commit=False)  # publish commits it with the delivery claim
    required = settings.chrysalis_fail_closed_all or (settings.chrysalis_fail_closed_high_risk and item.classification in HIGH_RISK)
    if required and row.status != "anchored":
        raise PermissionError("Chrysalis attestation is required before this release can publish")
    return row


def view(r: ChrysalisAnchor) -> dict:
    try: receipt = json.loads(r.receipt_json or "{}")
    except ValueError: receipt = {}
    return {"id": r.id, "anchor_type": r.anchor_type, "content_id": r.content_id, "content_hash": r.content_hash,
            "audit_head_hash": r.audit_head_hash, "payload_hash": r.payload_hash, "chrysalis_ref": r.chrysalis_ref,
            "status": r.status, "receipt": receipt, "error": r.error, "created_at": r.created_at, "anchored_at": r.anchored_at}
