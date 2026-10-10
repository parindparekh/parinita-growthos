"""Company-workspace credential vault; encryption key lives outside the database."""
import json
import os
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.orm import Session
from .config import settings
from .db import SessionLocal, get_db
from .models import ConnectorCredential
from .security import Principal, require_role
from .audit import record_event

router = APIRouter(prefix="/v1/connector-credentials", tags=["Account credentials"])


def cipher():
    if not settings.connector_encryption_key:
        raise ValueError("Credential storage is not configured on this workspace")
    return Fernet(settings.connector_encryption_key.encode())


def read_saved_secret(name):
    if not settings.connector_encryption_key:
        return ""
    with SessionLocal() as db:
        row = db.get(ConnectorCredential, name)
        if not row:
            return ""
        try:
            data = json.loads(cipher().decrypt(row.encrypted_value.encode()))
            if data["company_id"] != settings.company_id:
                raise ValueError("company mismatch")
            return data["value"]
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise ValueError("Saved credential cannot be unlocked for this workspace") from None


class CredentialInput(BaseModel):
    name: str = Field(pattern=r"^GROWTHOS_SECRET_[A-Z0-9_]+$", max_length=150)
    value: SecretStr


@router.get("", dependencies=[Depends(require_role("admin"))])
def inventory(db: Session = Depends(get_db)):
    return {"storage_configured":bool(settings.connector_encryption_key),
            "credentials":[{"name":r.name,"updated_at":r.updated_at} for r in db.query(ConnectorCredential).all()]}


@router.put("")
def save(req: CredentialInput, db: Session = Depends(get_db), p: Principal = Depends(require_role("admin"))):
    value = req.value.get_secret_value()
    if not value.strip() or len(value)>20000:
        raise HTTPException(422,"Credential must contain between 1 and 20000 characters")
    if os.getenv(req.name):
        raise HTTPException(409,"This credential is managed by the server; rotate it through the server secret manager")
    try:
        encrypted = cipher().encrypt(json.dumps({"company_id":settings.company_id,"value":value}).encode()).decode()
    except ValueError:
        raise HTTPException(503,"Credential storage is not configured on this workspace") from None
    row = db.get(ConnectorCredential,req.name) or ConnectorCredential(name=req.name)
    row.encrypted_value=encrypted; db.add(row)
    record_event(db,content_id=None,actor=p.name,action="credential.saved",details={"name":req.name})
    db.commit()
    return {"name":req.name,"saved":True}


@router.delete("/{name}")
def delete(name: str, db: Session = Depends(get_db), p: Principal = Depends(require_role("admin"))):
    row=db.get(ConnectorCredential,name)
    if not row:raise HTTPException(404,"Saved credential not found")
    db.delete(row)
    record_event(db,content_id=None,actor=p.name,action="credential.deleted",details={"name":name})
    db.commit()
    return {"deleted":True}
