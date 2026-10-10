"""Read-only setup state for an isolated company deployment."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .drafting import brand_profile
from .models import FeedEndpoint
from .connectors import endpoint_readiness
from .security import require_role
from . import model_runtime

router = APIRouter(prefix="/v1/workspace", tags=["Company setup"])


@router.get("/setup", dependencies=[Depends(require_role("admin"))])
def setup(db: Session = Depends(get_db)):
    endpoints = db.query(FeedEndpoint).all()
    sources = [x for x in endpoints if x.direction in {"inbound", "bidirectional"}]
    destinations = [x for x in endpoints if x.direction in {"outbound", "bidirectional"}]
    checks = [
        {"id":"company", "label":"Company workspace", "ready":bool(settings.company_id and settings.company_name),
         "detail":"Keep this company’s content and accounts in its own private workspace."},
        {"id":"identity", "label":"Company sign-in", "ready":bool(settings.sso_enabled and settings.company_id and settings.oidc_company_claim),
         "detail":"Only members of this company can sign in. Your workspace operator connects company sign-in."},
        {"id":"credentials", "label":"Secure account storage", "ready":bool(settings.connector_encryption_key), "detail":"Account credentials are encrypted and saved values are never displayed."},
        {"id":"brand", "label":"Brand voice", "ready":bool(brand_profile(db).name), "detail":"Define your company name, audience and writing style."},
        {"id":"model", "label":"Drafting model", "ready":model_runtime.configured(), "detail":"A drafting model is configured. Generate a draft to confirm it is available."},
        {"id":"sources", "label":"Source feeds", "ready":any(x.enabled for x in sources), "detail":"Connect approved source feeds or supply source material directly when drafting."},
        {"id":"destinations", "label":"Distribution", "ready":any(x.enabled and endpoint_readiness(x)["configuration_ready"] for x in destinations),
         "detail":"Each company supplies its own destination accounts. Live account acceptance remains separate."},
        {"id":"hosting", "label":"Public hosting", "ready":settings.is_production and settings.public_base_url.startswith("https://"),
         "detail":"Your workspace needs a secure public address and verified backups before launch."}]
    return {"company_id":settings.company_id, "company_name":settings.company_name or "Company workspace",
            "isolation":"dedicated_deployment", "checks":checks,
            "live_certified":False, "source_count":len(sources), "destination_count":len(destinations)}
