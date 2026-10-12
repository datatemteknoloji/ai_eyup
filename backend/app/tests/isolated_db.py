"""İzole test veritabanı — canlı uygulama verisine DOKUNMAZ (F.0).

Her pytest oturumunda aynı Postgres sunucusunda ``ainew_test_<rastgele>`` adlı GEÇİCİ bir veritabanı
açılır (CREATE DATABASE), yalnız gereken tablolar oluşturulur, oturum sonunda DROP edilir. Uygulamanın
``server_management`` veritabanına tek satır yazılmaz/okunmaz; DB durumuna bağlı ``skip`` yoktur.
Sunucuya ulaşılamazsa test SKIP değil FAIL olur (sessiz atlama yok).

Kullanım: ``from app.tests.isolated_db import isolated_db  # noqa: F401`` → ``db`` fixture'ı.
"""
from __future__ import annotations

import uuid
from typing import Iterator, List, Set

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker

# Yedekleme çerçevesi + bulgu deposu + ayarlar için gereken kök tablolar (FK kapanışı otomatik eklenir).
ROOT_TABLES = (
    "integration_instances", "bk_jobs", "bk_sessions", "bk_repositories", "bk_protected_objects",
    "bk_restore_points", "bk_proxies", "bk_rpo_policies", "bk_restore_tests", "servers", "infra_findings", "infra_finding_exceptions", "infra_check_runs",
    "app_settings", "infra_reference_data",
)

_STATE: dict = {}


def _closure(metadata, names) -> List:
    by_name = metadata.tables
    seen: Set[str] = set()
    stack = [n for n in names if n in by_name]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for fk in by_name[n].foreign_keys:
            stack.append(fk.column.table.name)
    return [t for t in metadata.sorted_tables if t.name in seen]


def _create() -> Engine:
    import app.models  # noqa: F401  (tüm modelleri metadata'ya kaydeder)
    from app.core.config import settings
    from app.core.database import Base
    url = make_url(settings.DATABASE_URL)
    name = f"ainew_test_{uuid.uuid4().hex[:10]}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    eng = create_engine(url.set(database=name), pool_pre_ping=True)
    Base.metadata.create_all(eng, tables=_closure(Base.metadata, ROOT_TABLES))
    _STATE.update(name=name, url=url)
    return eng


def _drop() -> None:
    eng = _STATE.pop("engine", None)
    if eng is not None:
        eng.dispose()
    name, url = _STATE.pop("name", None), _STATE.pop("url", None)
    if not name:
        return
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n"), {"n": name})
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def _isolated_engine() -> Iterator[Engine]:
    eng = _create()
    _STATE["engine"] = eng
    try:
        yield eng
    finally:
        _drop()


@pytest.fixture()
def isolated_db(_isolated_engine, monkeypatch):
    """Boş (TRUNCATE) izole DB oturumu. ``app.core.database.SessionLocal`` bu DB'ye yönlendirilir
    (kod içi ``SessionLocal()`` çağrıları da izole DB'yi görür). DEMO bayrağı AÇIK gelir; kapalı
    senaryolar ``monkeypatch.delenv("BACKUP_DEMO_ENABLED")`` ile test içinde kurulur."""
    import app.core.database as database
    from app.core.database import Base
    from app.services.capabilities import invalidate_capabilities
    tables = ", ".join(f'"{t.name}"' for t in _closure(Base.metadata, ROOT_TABLES))
    with _isolated_engine.begin() as c:
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    maker = sessionmaker(bind=_isolated_engine, autoflush=True, autocommit=False)
    monkeypatch.setattr(database, "SessionLocal", maker)
    monkeypatch.setenv("BACKUP_DEMO_ENABLED", "true")
    invalidate_capabilities()
    s = maker()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        invalidate_capabilities()
