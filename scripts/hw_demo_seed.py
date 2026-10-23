#!/usr/bin/env python3
"""Donanım DEMO verisi (Dell OME + HPE OneView fixture) — tek komutla eklenir, tek komutla silinir.

Kullanım (backend konteyneri içinde, repo kökünden; `.env` içinde HW_DEMO_ENABLED=true olmalı):
    docker exec -i server_management_backend python - seed    < scripts/hw_demo_seed.py
    docker exec -i server_management_backend python - cleanup < scripts/hw_demo_seed.py
    docker exec -i server_management_backend python - status  < scripts/hw_demo_seed.py

Ne yapar (seed):
- `integration_instances`: category=hardware, kind=hw_demo, `meta_json.demo_scale=large` (24 Dell + 2×16 HPE blade, alarm, garanti).
  Gerçek API'ye bağlanmaz (fixture). Gerçek bir donanım sağlayıcısı etkinleşince demo kendiliğinden yok sayılır.
- Eşleştirme denemesi için ETİKETLİ sahte hedefler: 6 fiziksel sunucu `zz-hwdemo-*` (IP yalnız 198.18.0.0/15, ai_ready=False
  → SSH/WinRM toplayıcıları atlar) + `ZZ-FAKE-vCenter` altındaki ilk 8 sahte ESXi host'a `DEMO…` seri numarası.
- Gerçek kayıtlara (ör. 192.168.1.101 gerçek ESXi hostu) DOKUNMAZ.

cleanup: demo instance'ı (hw_* satırları CASCADE ile gider), `zz-hwdemo-*` sunucuları ve ESXi `DEMO%` seri numaralarını geri alır.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.integration_instance import IntegrationInstance
from app.models.server import Server

CATEGORY, KIND = "hardware", "hw_demo"
LABEL = "DEMO donanım (fixture) — ZZ-HWDEMO"
SRV_PREFIX = "zz-hwdemo-"
FAKE_HV_NAME = "ZZ-FAKE-vCenter"


def _dell_serial(i: int) -> str:
    return f"DEMOD{i:02d}0001"


def _blade_serial(encl: int, bay: int) -> str:
    return f"DEMOH{encl}{bay:02d}0001"


def seed() -> None:
    from app.services.capabilities import invalidate_capabilities
    from app.services.hw.demo_gate import demo_enabled
    if not demo_enabled():
        print("HW_DEMO_ENABLED kapalı — önce .env'e HW_DEMO_ENABLED=true ekleyip backend+worker'ı yeniden oluşturun.")
        return
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        inst = db.query(IntegrationInstance).filter(IntegrationInstance.category == CATEGORY,
                                                    IntegrationInstance.kind == KIND).first()
        if inst is None:
            inst = IntegrationInstance(category=CATEGORY, kind=KIND, label=LABEL, endpoint="", verify_ssl=True,
                                       enabled=True, sync_interval_sec=900)
            db.add(inst)
        inst.meta_json = json.dumps({"demo_scale": "large",
                                     "intervals": {"alarm": 900, "inventory": 86400, "warranty": 86400}})
        inst.enabled = True

        # fiziksel sahte sunucular (Linux ×4, Windows ×2, eşleşmeyen ×1)
        specs = [(f"{SRV_PREFIX}lnx-{i:02d}", "rhel", _dell_serial(i)) for i in range(1, 5)]
        specs += [(f"{SRV_PREFIX}win-{i:02d}", "windows", _dell_serial(4 + i)) for i in range(1, 3)]
        specs += [(f"{SRV_PREFIX}lnx-09", "rhel", "DEMOX99999")]       # hiçbir donanım kaydıyla eşleşmez
        for n, (name, os_type, serial) in enumerate(specs, start=1):
            s = db.query(Server).filter(Server.name == name).first()
            if s is None:
                s = Server(name=name, hostname=name, ip_address=f"198.18.2.{n}", status="ONLINE", os_type=os_type,
                           os_version=("Windows Server 2022" if os_type == "windows" else "Red Hat Enterprise Linux 9.4"),
                           server_type="PHYSICAL", cpu_cores=32, memory_gb=256, tier="production",
                           node_exporter_installed=False, windows_exporter_installed=False, ai_ready=False)
                db.add(s)
            s.hw_serial, s.hw_collected_at = serial, now

        # ESXi sahte host'lar (ZZ-FAKE-vCenter altında) → blade seri numaraları
        from app.models.hypervisor import Hypervisor
        hv = db.query(Hypervisor).filter(Hypervisor.name == FAKE_HV_NAME).first()
        marked = 0
        if hv is not None:
            hosts = (db.query(HypervisorHostInventory).filter(HypervisorHostInventory.hypervisor_id == hv.id)
                     .order_by(HypervisorHostInventory.id).limit(8).all())
            for b, h in enumerate(hosts, start=1):
                h.serial_number, h.enclosure_serial = _blade_serial(1, b), "DEMOE10001"
                marked += 1
        db.commit()
        invalidate_capabilities()
        print(f"instance={inst.id} fiziksel_sunucu={len(specs)} esxi_isaretlenen={marked}")

        from app.services.hw.sync import sync_instance
        db.refresh(inst)
        r = sync_instance(db, inst, force=True)
        print("sync:", {k: r[k] for k in r if k in ("ok", "error", "skipped", "counts", "matching")} or r)
    finally:
        db.close()


def cleanup() -> None:
    from app.services.capabilities import invalidate_capabilities
    db = SessionLocal()
    try:
        n_inst = 0
        for inst in db.query(IntegrationInstance).filter(IntegrationInstance.category == CATEGORY,
                                                         IntegrationInstance.kind == KIND).all():
            db.delete(inst)
            n_inst += 1
        n_srv = db.query(Server).filter(Server.name.like(f"{SRV_PREFIX}%")).delete(synchronize_session=False)
        n_esx = (db.query(HypervisorHostInventory).filter(HypervisorHostInventory.serial_number.like("DEMO%"))
                 .update({"serial_number": None, "enclosure_serial": None}, synchronize_session=False))
        db.commit()
        invalidate_capabilities()
        print(f"silinen: instance={n_inst} sunucu={n_srv} esxi_seri_geri_alinan={n_esx}")
    finally:
        db.close()


def status() -> None:
    from sqlalchemy import func
    from app.models.hw import HwAlert, HwHostLink, HwServer
    db = SessionLocal()
    try:
        print("hw_servers:", db.query(func.count(HwServer.id)).scalar(),
              "hw_alerts:", db.query(func.count(HwAlert.id)).scalar(),
              "links:", db.query(func.count(HwHostLink.id)).scalar(),
              "zz-hwdemo servers:", db.query(func.count(Server.id)).filter(Server.name.like(f"{SRV_PREFIX}%")).scalar())
    finally:
        db.close()


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    {"seed": seed, "cleanup": cleanup, "status": status}.get(cmd, lambda: print(__doc__))()
