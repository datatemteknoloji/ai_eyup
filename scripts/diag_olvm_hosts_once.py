"""Datatem OLVM için TEK salt-okunur GET (`/hosts`) — host listesi (ad, durum, adres). Kimlik bilgisi YAZDIRILMAZ.
DB'ye yazmaz. Kullanım: python /tmp/diag_olvm_hosts_once.py "Datatem OLVM"
"""
from __future__ import annotations
import sys
from app.core.database import SessionLocal
from app.models.hypervisor import Hypervisor
from app.services.hypervisor_credentials import hv_password
from app.services.ovirt.ovirt_client import OVirtClient
from sqlalchemy import text


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "Datatem OLVM"
    db = SessionLocal()
    try:
        hv = db.query(Hypervisor).filter(Hypervisor.name == name).first()
        if not hv:
            print("hypervisor bulunamadı"); return 1
        c = OVirtClient(host=(hv.ip_address or hv.hostname or "").strip(), username=(hv.username or "").strip(),
                        password=hv_password(hv), port=hv.port or 443, verify_ssl=False)
        r = c._request("GET", "hosts", timeout=20)  # TEK GET
        print("HTTP", r.status_code)
        if r.status_code != 200:
            print("(cevap gövdesi yazdırılmadı)"); return 2
        hosts = (r.json() or {}).get("host") or []
        live = [{"name": h.get("name"), "status": h.get("status"), "address": h.get("address")} for h in hosts]
        print("canlı host sayısı:", len(live))
        for h in live: print("  ", h)
        rows = db.execute(text(
            "select m.host_name, max(m.timestamp) from hypervisor_host_metrics m "
            "join hypervisors h on h.id=m.hypervisor_id where h.name=:n group by 1 order by 1"), {"n": name}).all()
        print("DB host (son metrik):")
        for hn, ts in rows: print("  ", hn, ts)
        live_names = {h["name"] for h in live}
        print("DB'de olup canlıda olmayan:", [hn for hn, _ in rows if hn not in live_names])
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
