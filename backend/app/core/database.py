"""
Database configuration and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool
from typing import Generator
from app.core.config import settings

# Ana engine — FastAPI request/response için (async-safe pool)
# 5000 sunucu ölçeği: pool_size/max_overflow, Postgres max_connections=400
# (bkz. docker-compose.yml) ile birlikte yeterli tavan bırakacak şekilde
# yükseltildi — arka plan NullPool thread'lerine (toplu SSH/TCP/log işleri)
# de bağlantı payı kalıyor.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=40,
    max_overflow=80,
    pool_timeout=30,
    pool_recycle=1800,
    echo=False
)

# Thread engine — background thread'ler için (NullPool: her thread bağımsız bağlantı açar)
# NullPool = bağlantı paylaşımı yok → concurrent operation hatası olmaz
_thread_engine = create_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,
    echo=False
)

# FastAPI endpoint session factory (pool kullanır)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Background thread session factory (NullPool — paralel sync'ler için)
ThreadSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_thread_engine)

# Base class for models
Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — pooled session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
