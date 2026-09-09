"""metric_data yazma sözleşmesi: birincil anahtar ve çakışma toleransı.

Yaşanan hata: birincil anahtar YALNIZCA `timestamp` idi. Bir sync turunun tüm
satırları aynı zaman damgasını paylaştığı için ikinci satır "duplicate key" ile
düşüyor, tüm batch geri alınıyordu — tablo aylarca boş kaldı (0 chunk) ve VM
metrik geçmişi sessizce çalışmadı. Ayrıca Prometheus `query_range` her turda
örtüşen pencere döndürdüğü için aynı satır tekrar gelir; yazma bu tekrarı
hatasız atlamak zorunda.
"""
from app.models.metric import MetricData
from app.services.metric_sync import _insert_metric_rows


def test_primary_key_is_composite_and_includes_partition_column():
    pk = [c.name for c in MetricData.__table__.primary_key.columns]
    # TimescaleDB bölümleme kolonu anahtarda ZORUNLU.
    assert "timestamp" in pk
    # Satırı tekilleştiren kolonlar da olmalı; yoksa tek turda çakışma olur.
    assert set(pk) == {"timestamp", "server_id", "metric_name"}


def test_single_timestamp_batch_would_collide_without_composite_key():
    """Aynı turda aynı zaman damgalı çok satır normal senaryo — anahtar bunu
    desteklemek zorunda (regresyon bekçisi)."""
    pk = {c.name for c in MetricData.__table__.primary_key.columns}
    assert pk != {"timestamp"}


class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _FakeDb:
    def __init__(self, rowcount=None):
        self.statements = []
        self.commits = 0
        self._rowcount = rowcount

    def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeResult(
            self._rowcount if self._rowcount is not None else len(stmt._values or ())
        )

    def commit(self):
        self.commits += 1


_ROW = {
    "server_id": 47, "metric_name": "cpu_usage_percent", "value": 1.0,
    "unit": "percent", "labels": "vmware", "timestamp": "2026-01-01T12:00:00",
}


def test_insert_uses_on_conflict_do_nothing():
    db = _FakeDb(rowcount=1)
    _insert_metric_rows(db, [dict(_ROW)])
    stmt = db.statements[0]
    # ON CONFLICT olmadan örtüşen Prometheus penceresi her turda batch'i düşürür.
    assert stmt._post_values_clause is not None
    assert "DO NOTHING" in str(stmt).upper()
    assert db.commits == 1


def test_returns_actually_inserted_row_count():
    """Atlanan tekrarları 'yazıldı' saymak sync sayaçlarını şişirir."""
    db = _FakeDb(rowcount=0)
    assert _insert_metric_rows(db, [dict(_ROW), dict(_ROW)]) == 0


def test_falls_back_to_batch_size_when_driver_reports_unknown():
    db = _FakeDb(rowcount=-1)
    assert _insert_metric_rows(db, [dict(_ROW)]) == 1


def test_empty_batch_does_not_touch_db():
    db = _FakeDb()
    assert _insert_metric_rows(db, []) == 0
    assert db.statements == []
    assert db.commits == 0
