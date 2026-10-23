"""DEMO (fixture) donanım sağlayıcısı — yalnız HW_DEMO_ENABLED=true iken (dev). Gerçek veri DEĞİLDİR."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Set

from app.services.hw.constants import CAP_DEMO, KIND_DEMO
from app.services.hw.snapshot import (
    ALL_PARTS, AlertRec, EnclosureRec, HwSnapshot, ManagerRec, PART_ALERTS, PART_INVENTORY, PART_WARRANTY, ServerRec,
    WarrantyRec,
)
from app.services.integrations.types import ConnTestResult, ProviderHealth


class HwDemoProvider:
    kind = KIND_DEMO

    def __init__(self, row):
        self.row = row

    def capabilities(self) -> Set[str]:
        return {CAP_DEMO}          # "hw" yeteneğini AÇMAZ

    def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True)

    def test_connection(self) -> ConnTestResult:
        return ConnTestResult(True, api_version="demo", message="DEMO — fixture verisi (gerçek sağlayıcı değil)")

    def collect(self, parts: Iterable[str], *, since_alert: Optional[datetime] = None) -> HwSnapshot:
        parts = set(parts) & set(ALL_PARTS)
        now = datetime.now(timezone.utc)
        from app.services.integrations.registry import parse_meta
        if parse_meta(self.row).get("demo_scale") == "large":
            from app.services.hw.demo_fixture import build_large
            return build_large(parts, now)
        snap = HwSnapshot()
        snap.managers = [ManagerRec(key="demo-ome", kind="ome", name="DEMO OME", status="ok", server_count=3,
                                    version="4.7.0", support_level="verified"),
                         ManagerRec(key="demo-ov", kind="oneview", name="DEMO OneView", status="ok", server_count=3,
                                    version="10.00.00", support_level="verified")]
        if PART_INVENTORY in parts:
            snap.parts.add(PART_INVENTORY)
            for i in range(3):
                snap.servers.append(ServerRec(provider_ref=f"demo-d{i}", vendor="dell", name=f"demo-dell-{i}", manager_key="demo-ome",
                                              model="PowerEdge R750", serial=f"DEMOD{i}0001", bmc_ip=f"10.255.0.{10 + i}",
                                              bmc_type="iDRAC", bmc_version="7.00.00.00", form_factor="standalone",
                                              health=("critical" if i == 0 else "ok"), power_state="on"))
                snap.servers.append(ServerRec(provider_ref=f"demo-h{i}|/rest/server-hardware/{i}", vendor="hpe", name=f"Encl1, bay {i + 1}",
                                              manager_key="demo-ov", model="ProLiant BL460c Gen10", serial=f"DEMOH{i}0001",
                                              bmc_ip=f"10.255.1.{10 + i}", bmc_type="iLO5", bmc_version="2.78",
                                              form_factor="blade", enclosure_name="DEMO-Encl1", bay=str(i + 1),
                                              health=("warning" if i == 1 else "ok"), power_state="on"))
            snap.enclosures.append(EnclosureRec(provider_ref="demo-encl1", name="DEMO-Encl1", manager_key="demo-ov"))
            snap.complete_managers.update({"demo-ome", "demo-ov"})
        if PART_ALERTS in parts:
            snap.parts.add(PART_ALERTS)
            snap.alerts.append(AlertRec(provider_ref="demo-a1", severity="critical", message="DEMO: Güç kaynağı yedekliliği kayboldu",
                                        server_ref="demo-d0", manager_key="demo-ome", state="event",
                                        occurred_at=now - timedelta(hours=2), type_id="PSU0001"))
        if PART_WARRANTY in parts:
            snap.parts.add(PART_WARRANTY)
            snap.warranties.append(WarrantyRec(provider_ref="demo-w1", server_ref="demo-d1", serial="DEMOD10001",
                                               service_level="DEMO ProSupport", end_date=now - timedelta(days=30)))
        return snap
