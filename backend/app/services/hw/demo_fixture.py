"""DEMO (fixture) donanım verisi — "large" ölçeği. Deterministik (rastgelelik yok); gerçek veri DEĞİLDİR.

Yalnız `HwDemoProvider` kullanır (`meta_json.demo_scale == "large"`); varsayılan "small" fixture testlerdeki
sayılarla aynı kalır. Seri numaraları `DEMO` önekiyle başlar (`scripts/hw_demo_seed.py` eşleşme için aynı üretimi kullanır).

Kurgu:
  * OME: 24 Dell PowerEdge (standalone) — her 7'ncisi kritik, her 5'incisi uyarı.
  * OneView: 2 kasa (DEMO-Encl1/2) × 16 blade — kasa başına birkaç uyarı/kritik.
  * Alarmlar: kategori karışık (güç, fan, sıcaklık, bellek, disk), son 72 saate yayılmış.
  * Garanti: süresi dolmuş / 30 gün içinde / 90 gün içinde / uzak.
  * Bir yönetim noktası (`demo-ov2`) "erişilemedi" durumunda (UI'da hata satırı görünsün diye; envanteri tam sayılmaz).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Tuple

from app.services.hw.snapshot import AlertRec, EnclosureRec, HwSnapshot, ManagerRec, ServerRec, WarrantyRec

N_DELL = 24
N_ENCL = 2
BLADES_PER_ENCL = 16

_DELL_MODELS = ("PowerEdge R750", "PowerEdge R650", "PowerEdge R740xd", "PowerEdge R450")
_HPE_MODELS = ("ProLiant BL460c Gen10", "ProLiant BL460c Gen9")

_ALERT_KINDS: Tuple[Tuple[str, str, str, str], ...] = (
    ("PSU0001", "critical", "DEMO: Güç kaynağı yedekliliği kayboldu", "power"),
    ("FAN0002", "warning", "DEMO: Fan hızı eşiğin altında", "fan"),
    ("TMP0003", "warning", "DEMO: Sıcaklık uyarı eşiğini aştı", "thermal"),
    ("MEM0004", "critical", "DEMO: Düzeltilemeyen bellek hatası", "memory"),
    ("RAC0005", "warning", "DEMO: Disk öngörülü hata uyarısı", "storage"),
)


def dell_serial(i: int) -> str:
    return f"DEMOD{i:02d}0001"


def blade_serial(encl: int, bay: int) -> str:
    return f"DEMOH{encl}{bay:02d}0001"


def dell_ref(i: int) -> str:
    return f"demo-d{i}"


def blade_ref(encl: int, bay: int) -> str:
    return f"demo-h{encl}-{bay}|/rest/server-hardware/{encl}{bay:02d}"


def _health_dell(i: int) -> str:
    if i % 7 == 0:
        return "critical"
    if i % 5 == 0:
        return "warning"
    return "ok"


def _health_blade(encl: int, bay: int) -> str:
    if (encl + bay) % 9 == 0:
        return "critical"
    if (encl * 3 + bay) % 6 == 0:
        return "warning"
    return "ok"


def build_large(parts, now: datetime) -> HwSnapshot:
    from app.services.hw.snapshot import PART_ALERTS, PART_INVENTORY, PART_WARRANTY
    parts = set(parts)
    snap = HwSnapshot()
    snap.managers = [
        ManagerRec(key="demo-ome", kind="ome", name="DEMO OME", status="ok", server_count=N_DELL,
                   version="4.7.0", support_level="verified"),
        ManagerRec(key="demo-ov1", kind="oneview", name="DEMO OneView-1", status="ok",
                   server_count=BLADES_PER_ENCL, version="10.00.00", support_level="verified"),
        ManagerRec(key="demo-ov2", kind="oneview", name="DEMO OneView-2", status="ok",
                   server_count=BLADES_PER_ENCL, version="11.40.00", support_level="compatible"),
        ManagerRec(key="demo-ov3", kind="oneview", name="DEMO OneView-3 (erişilemiyor)", status="error",
                   error="DEMO: appliance zaman aşımı (fixture)", version="6.60.04", support_level="compatible"),
    ]
    refs: List[str] = []
    if PART_INVENTORY in parts:
        snap.parts.add(PART_INVENTORY)
        for i in range(1, N_DELL + 1):
            refs.append(dell_ref(i))
            snap.servers.append(ServerRec(
                provider_ref=dell_ref(i), vendor="dell", name=f"demo-dell-{i:02d}", manager_key="demo-ome",
                os_hostname=(f"zz-hwdemo-lnx-{i:02d}" if i <= 4 else None),
                model=_DELL_MODELS[i % len(_DELL_MODELS)], serial=dell_serial(i), bmc_ip=f"10.255.0.{10 + i}",
                bmc_type="iDRAC", bmc_version=("7.00.00.00" if i % 3 else "6.10.80.00"), form_factor="standalone",
                health=_health_dell(i), power_state="on", cpu_count=2, memory_gb=float(256 if i % 2 else 512),
                web_url=f"https://10.255.0.{10 + i}"))
        for e in range(1, N_ENCL + 1):
            mkey = "demo-ov1" if e == 1 else "demo-ov2"
            snap.enclosures.append(EnclosureRec(provider_ref=f"demo-encl{e}", name=f"DEMO-Encl{e}", manager_key=mkey,
                                                model="Synergy 12000 Frame", serial=f"DEMOE{e}0001", health="ok",
                                                bay_count=BLADES_PER_ENCL))
            for b in range(1, BLADES_PER_ENCL + 1):
                refs.append(blade_ref(e, b))
                snap.servers.append(ServerRec(
                    provider_ref=blade_ref(e, b), vendor="hpe", name=f"DEMO-Encl{e}, bay {b}", manager_key=mkey,
                    model=_HPE_MODELS[b % len(_HPE_MODELS)], serial=blade_serial(e, b),
                    bmc_ip=f"10.255.{e}.{10 + b}", bmc_type="iLO5", bmc_version=("2.78" if b % 4 else "2.55"),
                    form_factor="blade", enclosure_ref=f"demo-encl{e}", enclosure_name=f"DEMO-Encl{e}", bay=str(b),
                    health=_health_blade(e, b), power_state="on", cpu_count=2, memory_gb=384.0))
        snap.complete_managers.update({"demo-ome", "demo-ov1", "demo-ov2"})
    else:
        # envanter bu turda toplanmadı → alarm/garanti referansları için yine de ref listesi gerekir
        refs = [dell_ref(i) for i in range(1, N_DELL + 1)] + \
               [blade_ref(e, b) for e in range(1, N_ENCL + 1) for b in range(1, BLADES_PER_ENCL + 1)]
    if PART_ALERTS in parts:
        snap.parts.add(PART_ALERTS)
        n = 0
        for idx, ref in enumerate(refs):
            # her 3. sunucuda bir alarm; kritik/uyarı sağlıkla uyumlu kategoriler
            if idx % 3 != 0:
                continue
            type_id, sev, msg, cat = _ALERT_KINDS[idx % len(_ALERT_KINDS)]
            n += 1
            when = now - timedelta(hours=1 + (n * 5) % 72)
            cleared = (n % 4 == 0)
            snap.alerts.append(AlertRec(
                provider_ref=f"demo-a{n}", severity=sev, message=msg, server_ref=ref,
                manager_key=("demo-ome" if ref.startswith("demo-d") else
                             ("demo-ov1" if ref.startswith("demo-h1-") else "demo-ov2")),
                state="cleared" if cleared else "active", occurred_at=when,
                cleared_at=(when + timedelta(minutes=30) if cleared else None), type_id=type_id, category=cat))
    if PART_WARRANTY in parts:
        snap.parts.add(PART_WARRANTY)
        days = (-45, 12, 70, 400, 900)
        for idx, ref in enumerate(refs):
            snap.warranties.append(WarrantyRec(
                provider_ref=f"demo-w{idx + 1}", server_ref=ref,
                serial=(dell_serial(idx + 1) if ref.startswith("demo-d") else None),
                service_level="DEMO ProSupport", end_date=now + timedelta(days=days[idx % len(days)])))
    return snap
