"""Host ölçümü tazelik süzgeci — yeniden adlandırılan/envanterden çıkan host'un hayaleti.

`hypervisor_host_metrics` host başına zaman serisidir ve saklama süresi 90 gündür. Bir host
yeniden adlandırılır (ör. OLVM'de IP → `dtkvm01`) ya da envanterden kalkarsa eski adın son
satırı 90 gün boyunca "son ölçüm" olarak kalır; `DISTINCT ON (hypervisor_id, host_name)`
kullanan raporlar bunu ayrı bir host gibi listeler.

Kural (chat sayım kuralındaki `split_fresh` ile aynı fikir): bir host, **aynı hypervisor'ın
en yeni ölçümünden** `HOST_STALE_AFTER` kadar geride ise bayattır. Göreli ölçüt bilerek
seçildi: tüm hypervisor'ın toplaması günlerce durduysa host'lar bayat sayılmaz (kesinti
görünür kalır); yalnız bir host'un satırları kesilip kardeşleri sürüyorsa o host düşer.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

HOST_STALE_AFTER = timedelta(hours=24)


def _get(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def split_stale_hosts(
    rows: Iterable[Any],
    *,
    hv_of: Optional[Callable[[Any], Any]] = None,
    ts_of: Optional[Callable[[Any], Any]] = None,
    max_age: timedelta = HOST_STALE_AFTER,
) -> Tuple[List[Any], List[Any]]:
    """`rows`: host başına SON ölçüm satırları (dict ya da ORM/Row). (taze, bayat) döner.

    Zaman damgası olmayan satır bayat sayılmaz (ölçülemedi ≠ kesildi).
    """
    hv_of = hv_of or (lambda r: _get(r, "hypervisor_id"))
    ts_of = ts_of or (lambda r: _get(r, "timestamp"))
    items = list(rows)

    # Aynı host_ref (kalıcı kimlik) iki ad altında geldiyse (ör. IP → dtkvm01) yalnız en yeni
    # satır kalır; eski ad "yerine geçilmiş" sayılır. host_ref yoksa ad-bazlı davranış sürer.
    superseded: List[Any] = []
    best: Dict[Tuple[Any, str], Any] = {}
    for r in items:
        ref = str(_get(r, "host_ref") or "").strip()
        ts = ts_of(r)
        if not ref or ts is None:
            continue
        k = (hv_of(r), ref)
        cur = best.get(k)
        if cur is None or ts > ts_of(cur):
            best[k] = r
    if best:
        keep_ids = {id(v) for v in best.values()}
        kept: List[Any] = []
        for r in items:
            ref = str(_get(r, "host_ref") or "").strip()
            if ref and ts_of(r) is not None and id(r) not in keep_ids:
                superseded.append(r)
            else:
                kept.append(r)
        items = kept

    newest: Dict[Any, Any] = {}
    for r in items:
        ts = ts_of(r)
        if ts is None:
            continue
        hv = hv_of(r)
        if hv not in newest or ts > newest[hv]:
            newest[hv] = ts
    fresh: List[Any] = []
    stale: List[Any] = list(superseded)
    for r in items:
        ts = ts_of(r)
        top = newest.get(hv_of(r))
        if ts is not None and top is not None and (top - ts) > max_age:
            stale.append(r)
        else:
            fresh.append(r)
    return fresh, stale


def fresh_hosts(rows: Iterable[Any], **kw: Any) -> List[Any]:
    return split_stale_hosts(rows, **kw)[0]
