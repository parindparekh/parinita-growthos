"""Schema bootstrap.

- create_all for new tables,
- additive column upgrade for databases created by v1.0,
- append-only triggers on audit_events (UPDATE/DELETE/TRUNCATE rejected by the database).

A database superuser can still drop the triggers; the hash chain (and anchoring its
head outside the database) is what makes that detectable. For anything beyond additive
changes, adopt Alembic.
"""
import logging
from sqlalchemy import inspect, text
from .db import Base, engine
from . import models  # noqa: F401  (register tables)

log = logging.getLogger("growthos.migrate")
_LOCK_KEY = 727273


def _literal(col):
    d = col.default
    if d is None or not getattr(d, "is_scalar", False):
        return None
    v = d.arg
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _add_missing_columns(conn):
    insp = inspect(conn)
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(conn.dialect)}'
            lit = _literal(col)
            if lit is not None:
                ddl += f" DEFAULT {lit}"
            conn.execute(text(ddl))
            if table.name == "audit_events" and col.name == "hash_version":
                # Rows that predate the column were hashed with the v1.0 scheme. Runs before triggers exist.
                conn.execute(text("UPDATE audit_events SET hash_version = 1"))
            log.info("schema upgrade: added %s.%s", table.name, col.name)


def _install_audit_triggers(conn):
    if conn.dialect.name == "postgresql":
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION growthos_audit_append_only() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'audit_events is append-only'; END; $$ LANGUAGE plpgsql"""))
        conn.execute(text("DROP TRIGGER IF EXISTS growthos_audit_no_mutation ON audit_events"))
        conn.execute(text("""CREATE TRIGGER growthos_audit_no_mutation BEFORE UPDATE OR DELETE ON audit_events
                             FOR EACH ROW EXECUTE FUNCTION growthos_audit_append_only()"""))
        conn.execute(text("DROP TRIGGER IF EXISTS growthos_audit_no_truncate ON audit_events"))
        conn.execute(text("""CREATE TRIGGER growthos_audit_no_truncate BEFORE TRUNCATE ON audit_events
                             FOR EACH STATEMENT EXECUTE FUNCTION growthos_audit_append_only()"""))
    elif conn.dialect.name == "sqlite":
        for op in ("UPDATE", "DELETE"):
            conn.execute(text(f"""CREATE TRIGGER IF NOT EXISTS growthos_audit_no_{op.lower()} BEFORE {op} ON audit_events
                                  BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"""))


def init_db(bind=None):
    with (bind or engine).begin() as conn:
        if conn.dialect.name == "postgresql":
            # Serialise concurrent replicas doing DDL at boot.
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
        Base.metadata.create_all(bind=conn)
        _add_missing_columns(conn)
        _install_audit_triggers(conn)


def schema_ready() -> bool:
    with engine.connect() as conn:
        return {"content_items", "feed_endpoints", "audit_events", "deliveries"} <= set(inspect(conn).get_table_names())
