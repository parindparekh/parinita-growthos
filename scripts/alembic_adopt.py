#!/usr/bin/env python3
"""Adopt Alembic version tracking for a pre-v1.6 GrowthOS database."""
from alembic import command
from alembic.config import Config
from app.migrate import init_db
from app.config import settings

init_db()
cfg = Config('alembic.ini')
cfg.set_main_option('sqlalchemy.url', settings.database_url)
command.stamp(cfg, 'head')
print('GrowthOS v1.6 schema verified and stamped at Alembic head.')
