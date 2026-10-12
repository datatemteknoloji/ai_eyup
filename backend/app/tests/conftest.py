"""Ortak pytest fixture'ları. İzole Postgres veritabanı fixture'ı: bkz. ``isolated_db.py``."""
from app.tests.isolated_db import _isolated_engine, isolated_db  # noqa: F401
