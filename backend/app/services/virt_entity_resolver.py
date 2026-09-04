"""Virt envanter — mesajdan GERÇEK (DB'de kayıtlı) varlık adı çıkarımı.

Genel kural (datastore'a özel DEĞİL): kullanıcı mesajında bilinen bir VM,
datastore, ESX host veya cluster adı geçiyorsa bunu TAHMİN ETMEDEN, doğrudan
DB'deki gerçek adlarla karşılaştırarak bulur. "NVME_DS'de hangi VM'ler var"
sorusu için olduğu gibi, "web01'in diskleri" veya "esx03'teki VM'ler" gibi
herhangi bir isimlendirilmiş varlık sorusu için de aynı mekanizma çalışır.

Neden regex tahmini değil de DB lookup: adların formatı öngörülemez
(büyük/küçük harf, alt çizgi, tire, sayı...) — ama DB'de zaten kayıtlı, o
yüzden "bu isimlerden biri mesajda geçiyor mu?" sorusu regex kurmaktan çok
daha güvenilir ve GENEL (yeni bir isimlendirme deseni için kod değişikliği
gerekmez).
"""
from __future__ import annotations

import re
import time
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

_MIN_NAME_LEN = 3
_TTL_SEC = 60.0
_cache: Dict[str, Tuple[float, List[str]]] = {}


def _cached(key: str, loader: Callable[[], List[str]]) -> List[str]:
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < _TTL_SEC:
        return hit[1]
    try:
        names = loader()
    except Exception:
        names = []
    _cache[key] = (now, names)
    return names


def _clean_sorted(values) -> List[str]:
    """Benzersiz, min uzunluk filtreli, EN UZUNDAN başlayarak sıralı isim listesi.

    Uzundan kısaya sıralama önemli: "web01" ile "web010" ikisi de mesajda
    geçiyorsa daha spesifik (uzun) olan önce denenir.
    """
    seen = {(v or "").strip() for v in values if v and len((v or "").strip()) >= _MIN_NAME_LEN}
    return sorted(seen, key=len, reverse=True)


def _known_vm_names(db: Session) -> List[str]:
    def _load() -> List[str]:
        from app.models.server import Server
        from app.services.platform_scope import vm_filter_condition

        rows = db.query(Server.vm_name).filter(vm_filter_condition()).all()
        return _clean_sorted(r[0] for r in rows)

    return _cached("vm_name", _load)


def _known_datastore_names(db: Session) -> List[str]:
    def _load() -> List[str]:
        from app.models.virt_datastore import VirtDatastore

        rows = db.query(VirtDatastore.name).distinct().all()
        return _clean_sorted(r[0] for r in rows)

    return _cached("datastore_name", _load)


def _known_host_names(db: Session) -> List[str]:
    def _load() -> List[str]:
        from app.models.hypervisor_metric import HypervisorHostMetric

        rows = db.query(HypervisorHostMetric.host_name).distinct().all()
        return _clean_sorted(r[0] for r in rows)

    return _cached("esx_host_name", _load)


def _known_cluster_names(db: Session) -> List[str]:
    def _load() -> List[str]:
        from app.models.server import Server
        from app.services.platform_scope import vm_filter_condition

        rows = db.query(Server.vm_cluster).filter(vm_filter_condition()).distinct().all()
        return _clean_sorted(r[0] for r in rows)

    return _cached("cluster_name", _load)


def _find_match(message_lower: str, candidates: List[str]) -> Optional[str]:
    """candidates uzundan kısaya sıralı — kelime sınırlı (word-boundary) ilk eşleşme."""
    for name in candidates:
        pattern = r"(?<![a-z0-9_])" + re.escape(name.lower()) + r"(?![a-z0-9_])"
        if re.search(pattern, message_lower):
            return name
    return None


def extract_entity_filters(db: Session, message: str) -> Dict[str, str]:
    """Mesajda geçen BİLİNEN (DB'de kayıtlı) varlık adlarını bulur.

    Dönen anahtarlar: vm_name, datastore, host_name, cluster — hiçbiri
    bulunmazsa boş dict döner (mevcut "filtresiz/tümü" davranışı korunur,
    yanlış negatifte veri kaybı olmaz — yalnız daraltma fırsatı kaçırılır).
    """
    m = (message or "").lower().strip()
    if not m:
        return {}

    out: Dict[str, str] = {}
    ds = _find_match(m, _known_datastore_names(db))
    if ds:
        out["datastore"] = ds
    vm = _find_match(m, _known_vm_names(db))
    if vm:
        out["vm_name"] = vm
    host = _find_match(m, _known_host_names(db))
    if host:
        out["host_name"] = host
    cl = _find_match(m, _known_cluster_names(db))
    if cl:
        out["cluster"] = cl
    return out
