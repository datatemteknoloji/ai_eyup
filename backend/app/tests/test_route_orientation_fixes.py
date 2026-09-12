"""Yönelim yamaları — esnaf ezmesi, olumsuzluk, knowledge+host, Linux inventory."""
from app.services.admin_intent_router import route_admin_question
from app.services.chat_path_policy import is_knowledge_only
from app.services.linux_chat_intent import is_fleet_inventory_query
from app.services.module_orchestrator import plan_modules
from app.services.unified_intent_router import route_unified
from app.services.virt_fleet_perf import wants_live_virt_sample


AV1 = (
    "Filodaki VM'lerin CPU kullanımı yüzde 90'ın üzerinde olanları "
    "host kırılımıyla sırala; anlık demiyorum, son sync yeterli."
)
L2 = (
    "olvm manager sunucusunun canlı SSH ile failed systemd unit'lerini ve "
    "son journal kritiklerini tara; vCenter event listesine düşme."
)
L3 = (
    "RAID5 ile RAID10 farkını genel anlat, sonra minio1'de mdstat/mdadm "
    "gerçek dizilimi ayrı tut — tanım ile canlı array'i karıştırma."
)
L4 = (
    "Tüm Linux filonun hostname, OS sürümü ve AI-ready özeti — "
    "her hosta SSH ile df çekmeden envanter özeti ver."
)
L5 = (
    "minio1 (Linux) ile Winserver01 (Windows) kaynak kullanımını karşılaştır; "
    "peki CPU? Windows'u Linux SSH'e veya VM QueryPerf'e kaydırma."
)


def test_av1_virt_only_not_live_sample():
    plan = plan_modules(AV1)
    assert "virt" in plan.modules
    assert "linux" not in plan.modules
    assert wants_live_virt_sample(AV1) is False
    ru = route_unified(AV1)
    assert ru.mode == "live"
    assert "virt" in ru.modules
    assert "linux" not in ru.modules


def test_l5_linux_windows_not_virt():
    plan = plan_modules(L5)
    assert "linux" in plan.modules
    assert "windows" in plan.modules
    assert "virt" not in plan.modules


def test_l2_linux_not_virt_not_inventory():
    ru = route_unified(L2)
    assert ru.mode == "live"
    assert "linux" in ru.modules
    assert "virt" not in ru.modules
    adm = route_admin_question(L2, "linux")
    assert adm.intent != "inventory"
    assert adm.intent in ("ssh_topic", "llm", "direct_cmd")
    assert is_fleet_inventory_query(L2) is False
    assert wants_live_virt_sample(L2) is False


def test_l3_not_knowledge_only_linux():
    assert is_knowledge_only(L3) is False
    assert is_knowledge_only("RAID5 ile RAID10 farkı nedir?") is True
    ru = route_unified(L3)
    assert ru.mode == "live"
    assert "linux" in ru.modules


def test_l4_inventory_summary_unchanged():
    adm = route_admin_question(L4, "linux")
    assert adm.intent == "inventory_summary"
    ru = route_unified(L4)
    assert ru.modules == ("linux",) or ru.modules[0] == "linux"
