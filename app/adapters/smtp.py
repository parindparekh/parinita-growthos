import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from ..config import settings
from . import Adapter, DeliveryResult, register


def send_mail(to: list[str], subject: str, body: str, message_id_seed: str, content_hash: str = "") -> DeliveryResult:
    """Shared by the smtp and pr_wire adapters."""
    if not settings.smtp_host or not settings.smtp_from:
        return DeliveryResult(ok=False, detail="SMTP_HOST and SMTP_FROM must be configured", attempts=0)
    msg = EmailMessage()
    try:
        msg["From"] = settings.smtp_from
        msg["To"] = ", ".join(str(t) for t in to)
        msg["Subject"] = subject.replace("\r", " ").replace("\n", " ")
        msg["Message-ID"] = make_msgid(idstring=message_id_seed)
        msg["X-GrowthOS-Content-Hash"] = content_hash
    except ValueError as exc:  # header injection attempt
        return DeliveryResult(ok=False, detail=f"invalid header: {exc}", attempts=0)
    msg.set_content(body)
    ctx = ssl.create_default_context()
    try:
        if settings.smtp_port == 465:  # implicit TLS
            client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.http_timeout_seconds, context=ctx)
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.http_timeout_seconds)
        with client as s:
            if settings.smtp_port != 465 and settings.smtp_use_tls:
                s.starttls(context=ctx)
            if settings.smtp_username:
                s.login(settings.smtp_username, settings.smtp_password)
            refused = s.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        return DeliveryResult(ok=False, detail=f"{type(exc).__name__}: {exc}"[:500])
    return DeliveryResult(ok=True, provider_id=msg["Message-ID"], detail=f"recipients={len(to)} refused={len(refused or {})}")


class SmtpAdapter(Adapter):
    protocols = {"smtp"}

    def check_config(self, url, cfg):
        return "" if cfg.get("to") else "smtp endpoints need config.to (one or more recipients)"

    def send(self, payload, endpoint, cfg, idempotency_key, resume=""):
        to = cfg.get("to") or []
        to = [to] if isinstance(to, str) else list(to)
        if not to:
            return DeliveryResult(ok=False, detail="SMTP endpoint requires config.to", attempts=0)
        body = payload["body"] + (f"\n\n{payload['cta_url']}" if payload.get("cta_url") else "")
        return send_mail(to, str(cfg.get("subject_prefix", "")) + payload["title"], body, idempotency_key, payload.get("content_hash", ""))


register(SmtpAdapter())
