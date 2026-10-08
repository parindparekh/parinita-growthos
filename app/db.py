import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool
from .config import settings

_url = settings.database_url
_kwargs: dict = {"pool_pre_ping": True}
if _url.startswith("sqlite"):
    _kwargs["connect_args"] = {"check_same_thread": False}
    _path = make_url(_url).database
    if _path and _path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(_path)), exist_ok=True)
    if ":memory:" in _url:
        # One shared connection, otherwise every connection gets its own empty database.
        _kwargs["poolclass"] = StaticPool
engine = create_engine(_url, **_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
