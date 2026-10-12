"""Kapasite eşikleri — `capacity_policies` tablosu (global kapsam).

Varsayılanlar kod içinde; tabloda yalnız değiştirilen anahtarlar tutulur.
Planlayıcı (`virt_capacity_planner`) eşikleri `active()` ile okur; `build_capacity`
çağrısı başında `activate(db)` eşikleri tabloda okuyup ContextVar'a yazar.
Böylece aynı istek/iş içindeki tüm hesap (runway, N+1, what-if, bulgular) aynı eşikleri görür.
"""
from __future__ import annotations

import contextvars
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.capacity_policy import CapacityPolicy

# anahtar → (varsayılan, min, max, açıklama)
SPEC: Dict[str, Dict[str, Any]] = {
    "memory": {"default": 85.0, "min": 50.0, "max": 99.0,
               "label": "Memory doluluk eşiği (%)",
               "hint": "Effective Memory bu oranı aşınca tükenme/yerleşim 'sığmaz' sayılır."},
    "cpu": {"default": 80.0, "min": 30.0, "max": 99.0,
            "label": "CPU doluluk eşiği (%)", "hint": "CPU aşımı yalnız uyarıdır (VM'ler yavaşlar ama çalışır)."},
    "datastore": {"default": 85.0, "min": 50.0, "max": 99.0,
                  "label": "Datastore doluluk eşiği (%)", "hint": "Kullanım bu oranı aşınca bulgu açılır."},
    "n1_warn": {"default": 90.0, "min": 50.0, "max": 100.0,
                "label": "N+1 uyarı eşiği (%)",
                "hint": "En büyük host düşünce kalan Memory'nin doluluğu; 100'ü aşarsa N+1 bozulur."},
    "vcpu_ratio": {"default": 4.0, "min": 1.0, "max": 32.0,
                   "label": "vCPU:çekirdek oranı uyarısı", "hint": "Oran bu değeri aşınca düşük öncelikli bulgu."},
    "rs_window_days": {"default": 30.0, "min": 7.0, "max": 90.0,
                       "label": "Aşırı boyut: gözlem penceresi (gün)",
                       "hint": "Aşırı boyutlu VM tespiti ve right-size önerisi bu kadar günlük p95 CPU'ya bakar."},
    "rs_target_pct": {"default": 70.0, "min": 40.0, "max": 90.0,
                      "label": "Right-size hedef CPU doluluğu (%)",
                      "hint": "Önerilen vCPU, p95 talebi bu doluluğa oturtacak şekilde hesaplanır (güvenlik payı = 100 - hedef)."},
    "rs_min_reduction_pct": {"default": 25.0, "min": 10.0, "max": 75.0,
                             "label": "Aşırı boyut: asgari küçülme (%)",
                             "hint": "VM, önerilen vCPU mevcut vCPU'dan en az bu oranda azsa 'aşırı boyutlu' sayılır."},
    "rs_min_vcpu": {"default": 4.0, "min": 2.0, "max": 64.0,
                    "label": "Aşırı boyut: asgari vCPU",
                    "hint": "Bundan az vCPU'lu VM'ler küçültme adayı sayılmaz (kazanç ihmal edilebilir)."},
    "ds_reserve": {"default": 15.0, "min": 0.0, "max": 50.0,
                   "label": "Datastore boş alan rezervi (%)",
                   "hint": "Yerleşim/what-if hesabında datastore'da korunan boş alan."},
}

_ACTIVE: contextvars.ContextVar[Optional[Dict[str, float]]] = contextvars.ContextVar("cap_thresholds", default=None)


def defaults() -> Dict[str, float]:
    return {k: float(v["default"]) for k, v in SPEC.items()}


def load(db: Session) -> Dict[str, float]:
    out = defaults()
    try:
        for row in db.query(CapacityPolicy).all():
            if row.key in SPEC and row.value is not None:
                out[row.key] = float(row.value)
    except Exception:  # noqa: BLE001 — tablo henüz yoksa varsayılanlar
        db.rollback()
    return out


def activate(db: Optional[Session] = None, values: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Geçerli bağlam için eşikleri ayarlar (db'den ya da verilen değerlerden)."""
    th = defaults()
    if values:
        th.update({k: float(v) for k, v in values.items() if k in SPEC and v is not None})
    elif db is not None:
        th = load(db)
    _ACTIVE.set(th)
    return th


def active() -> Dict[str, float]:
    return _ACTIVE.get() or defaults()


def validate(values: Dict[str, Any]) -> Dict[str, float]:
    clean: Dict[str, float] = {}
    for k, v in (values or {}).items():
        if k not in SPEC:
            raise ValueError(f"Bilinmeyen eşik: {k}")
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{k}: sayı olmalı")
        s = SPEC[k]
        if not (s["min"] <= f <= s["max"]):
            raise ValueError(f"{k}: {s['min']:g}–{s['max']:g} aralığında olmalı")
        clean[k] = f
    return clean


def save(db: Session, values: Dict[str, Any], user: str = "") -> Dict[str, float]:
    clean = validate(values)
    for k, v in clean.items():
        row = db.query(CapacityPolicy).filter(CapacityPolicy.key == k).first()
        if v == SPEC[k]["default"]:
            if row is not None:       # varsayılana dönüş → satırı sil
                db.delete(row)
            continue
        if row is None:
            db.add(CapacityPolicy(key=k, value=v, updated_by=user or None))
        else:
            row.value, row.updated_by = v, user or None
    db.commit()
    return load(db)


def payload(db: Session) -> Dict[str, Any]:
    cur = load(db)
    return {
        "values": cur,
        "defaults": defaults(),
        "spec": {k: {"label": s["label"], "hint": s["hint"], "min": s["min"], "max": s["max"],
                     "default": s["default"], "overridden": cur[k] != s["default"]}
                 for k, s in SPEC.items()},
    }
