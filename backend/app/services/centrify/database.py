"""Centrify modülü veritabanı bağlantısı — ayrı Postgres container (:5434).

ainew ana DB'den tamamen bağımsız. Bağlantı yoksa modül devre dışı kalır,
ainew çalışmaya devam eder.
"""
from __future__ import annotations

import logging
import os
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

CentrifyBase = declarative_base()

_engine = None
_session_factory = None
_thread_engine = None
_thread_session_factory = None


def _get_url() -> str:
    return os.environ.get(
        "CENTRIFY_DATABASE_URL",
        "postgresql://centrify:centrify@localhost:5434/centrify_zone_mgmt",
    )


def _ensure_engine():
    global _engine, _session_factory
    if _engine is not None:
        return
    url = _get_url()
    if not url:
        logger.warning("CENTRIFY_DATABASE_URL tanımlı değil — Centrify DB devre dışı")
        return
    _engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_timeout=15,
        pool_recycle=1800,
        echo=False,
    )
    _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _ensure_thread_engine():
    global _thread_engine, _thread_session_factory
    if _thread_engine is not None:
        return
    url = _get_url()
    if not url:
        return
    _thread_engine = create_engine(url, poolclass=NullPool, echo=False)
    _thread_session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=_thread_engine
    )


def get_centrify_db() -> Generator[Session, None, None]:
    """FastAPI dependency — Centrify DB session."""
    _ensure_engine()
    if _session_factory is None:
        raise RuntimeError("Centrify DB bağlantısı yapılandırılmamış")
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()


def get_centrify_thread_session() -> Optional[Session]:
    """Arka plan iş parçacıkları için session (NullPool)."""
    _ensure_thread_engine()
    if _thread_session_factory is None:
        return None
    return _thread_session_factory()


def centrify_db_available() -> bool:
    """Centrify DB erişilebilir mi?"""
    try:
        _ensure_engine()
        if _engine is None:
            return False
        with _engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


def create_centrify_tables() -> bool:
    """Centrify tablolarını oluştur (ilk kurulumda). True = başarılı."""
    try:
        _ensure_engine()
        if _engine is None:
            return False
        import app.models.centrify_zone  # noqa: F401 — modelleri CentrifyBase.metadata'ya kaydet
        CentrifyBase.metadata.create_all(bind=_engine)
        logger.info("Centrify DB tabloları oluşturuldu (%d tablo)", len(CentrifyBase.metadata.tables))
        return True
    except Exception as exc:
        logger.error("Centrify tablo oluşturma hatası: %s", exc)
        return False
