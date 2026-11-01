__version__ = 1

# SQLAlchemy 2.1: ``postgresql://`` URL'sinin varsayılan sürücüsü psycopg2'den psycopg (v3)'e değişti.
# Mevcut kurulumların .env dosyaları ``postgresql://`` kullanıyor ve sürücü davranışı (parametre bağlama,
# JSON/Decimal/zaman dilimi dönüşümleri, pool) değişmesin diye psycopg2 sürücüsü AÇIKÇA korunur.
# ``postgresql+psycopg://`` gibi sürücüsü belirtilmiş URL'ler etkilenmez. (SQLAlchemy 2.0'da da zararsız.)
try:  # pragma: no cover - import yan etkisi
    from sqlalchemy.dialects import registry as _sa_registry

    _sa_registry.register(
        "postgresql", "sqlalchemy.dialects.postgresql.psycopg2", "PGDialect_psycopg2"
    )
except Exception:  # SQLAlchemy yoksa / API değiştiyse uygulama yine açılsın
    pass
