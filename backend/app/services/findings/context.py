"""Bulgu bağlamı: host düşerse etki + aynı host'taki ilişkili bulgular ((a) aynı olay / (b) diğer) + sensör türüne göre genel rehber.

Hepsi deterministiktir (AI yok). Rehber metinleri satıcıdan bağımsız GENEL operasyon adımlarıdır; komut, KB numarası,
firmware sürümü veya satıcı bağlantısı içermez. Satıcı (Dell/HPE/Lenovo/Cisco) resmî bilgi bankası bağlantıları
`reference_sources.json` içinde doğrulanmadıkça gösterilmez (bağlantı uydurulmaz).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.infra_finding import InfraFinding
from app.services.capacity import hierarchy as cap_hier
from app.services import reference_sources

_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# check_id → rehber uygulanır mı (sensör kaynaklı donanım bulguları)
_SENSOR_CHECKS = {"hw.host.sensor_alarm", "hw.host.sensor_repeat", "hw.host.overall_status"}

# sensör türü anahtar kelimesi → rehber anahtarı
_TYPE_KEYS = (("power", "power"), ("psu", "power"), ("temp", "temperature"), ("fan", "fan"), ("volt", "voltage"),
              ("battery", "battery"), ("storage", "storage"), ("disk", "storage"), ("memory", "memory"),
              ("processor", "processor"), ("cpu", "processor"))

# (neden, etki, adımlar) — TR/EN. "Olası" ifadeleri bilinçli: sensör durumu tek başına kök nedeni kanıtlamaz.
_GUIDES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "power": {
        "tr": {"title": "Güç kaynağı / güç sensörü",
               "cause": "Olası nedenler: güç kaynağı (PSU) arızası, güç kablosu/PDU hattı kesintisi, yedekli PSU'lardan birinin kapalı olması.",
               "impact": "Yedeklilik azalmış olabilir; kalan PSU de düşerse host kapanır.",
               "steps": ["Host'un BMC/yönetim kartı (iDRAC/iLO/IMC vb.) sistem olay günlüğünde (SEL) PSU olaylarını kontrol edin.",
                         "Fiziksel PSU LED'lerini ve her PSU'nun güç kablosu/PDU bağlantısını kontrol edin.",
                         "Sorun sürüyorsa donanım satıcısı desteğiyle PSU değişimi planlayın; değişimden önce host'u bakım moduna almayı değerlendirin."]},
        "en": {"title": "Power supply / power sensor",
               "cause": "Possible causes: power supply (PSU) failure, power cable/PDU feed loss, one of the redundant PSUs being off.",
               "impact": "Redundancy may be reduced; if the remaining PSU also fails the host powers off.",
               "steps": ["Check PSU events in the host's BMC/management controller (iDRAC/iLO/IMC etc.) system event log (SEL).",
                         "Check the physical PSU LEDs and each PSU's power cable/PDU connection.",
                         "If the issue persists, plan a PSU replacement with the hardware vendor's support; consider putting the host in maintenance mode first."]},
    },
    "temperature": {
        "tr": {"title": "Sıcaklık sensörü",
               "cause": "Olası nedenler: fan arızası, tıkalı hava akışı, oda/soğutma sorunu, yüksek yük.",
               "impact": "Sürekli yüksek sıcaklıkta işlemci kısıtlaması (performans düşüşü) veya koruyucu kapanma olabilir.",
               "steps": ["Aynı host'ta fan sensörü alarmı olup olmadığını kontrol edin.",
                         "Raf/oda sıcaklığını ve ön-arka hava akışını (boş slot kapakları, kablo yığılması) kontrol edin.",
                         "BMC/yönetim kartı günlüğündeki sıcaklık olaylarının zamanını izleyin; tekrarlıyorsa donanım desteğine açın."]},
        "en": {"title": "Temperature sensor",
               "cause": "Possible causes: fan failure, blocked airflow, room/cooling problem, high load.",
               "impact": "Sustained high temperature may cause CPU throttling (performance loss) or a protective shutdown.",
               "steps": ["Check whether the same host has a fan sensor alarm.",
                         "Check rack/room temperature and front-to-back airflow (blanking panels, cable build-up).",
                         "Watch the timing of temperature events in the BMC/management controller log; open a hardware support case if they repeat."]},
    },
    "fan": {
        "tr": {"title": "Fan sensörü",
               "cause": "Olası nedenler: fan arızası/yavaşlaması, fan modülünün gevşek takılı olması, toz.",
               "impact": "Soğutma azalır; sıcaklık alarmına ve performans kısıtlamasına yol açabilir.",
               "steps": ["Hangi fan modülünün alarm verdiğini BMC/yönetim kartı günlüğünden belirleyin.",
                         "Fan modülünün yerine oturduğunu ve çevresinin temiz olduğunu kontrol edin.",
                         "Alarm sürerse donanım desteğiyle fan değişimi planlayın."]},
        "en": {"title": "Fan sensor",
               "cause": "Possible causes: fan failure/slowdown, loosely seated fan module, dust.",
               "impact": "Cooling is reduced; may lead to temperature alarms and performance throttling.",
               "steps": ["Identify which fan module is alarming from the BMC/management controller log.",
                         "Check that the fan module is seated and its surroundings are clean.",
                         "If the alarm persists, plan a fan replacement with hardware support."]},
    },
    "voltage": {
        "tr": {"title": "Voltaj sensörü",
               "cause": "Olası nedenler: güç kaynağı veya anakart voltaj regülasyonu sorunu.",
               "impact": "Kararsızlık veya beklenmeyen yeniden başlatma riski.",
               "steps": ["BMC/yönetim kartı günlüğünde voltaj olaylarını ve aynı anda gelen PSU olaylarını kontrol edin.",
                         "Sorun tekrarlıyorsa donanım desteğine açın."]},
        "en": {"title": "Voltage sensor",
               "cause": "Possible causes: power supply or system-board voltage regulation issue.",
               "impact": "Risk of instability or unexpected restarts.",
               "steps": ["Check voltage events and any simultaneous PSU events in the BMC/management controller log.",
                         "Open a hardware support case if it repeats."]},
    },
    "storage": {
        "tr": {"title": "Depolama / disk sensörü",
               "cause": "Olası nedenler: disk veya RAID denetleyici sorunu, degrade RAID, disk yedeğinin devreye girmesi.",
               "impact": "Yedeklilik azalmış olabilir; ek disk arızasında veri kaybı riski.",
               "steps": ["RAID denetleyici/BMC günlüğünden disk ve sanal disk durumunu doğrulayın.",
                         "Yedeklilik tamamlanana (rebuild bitene) kadar bu host'taki kritik veriyi yedeklediğinizden emin olun.",
                         "Arızalı disk için donanım desteğiyle değişim planlayın."]},
        "en": {"title": "Storage / disk sensor",
               "cause": "Possible causes: disk or RAID controller issue, degraded RAID, spare disk activation.",
               "impact": "Redundancy may be reduced; risk of data loss on an additional disk failure.",
               "steps": ["Verify disk and virtual disk state from the RAID controller/BMC log.",
                         "Make sure critical data on this host is backed up until redundancy is restored (rebuild finished).",
                         "Plan a replacement of the failed disk with hardware support."]},
    },
    "battery": {
        "tr": {"title": "Batarya sensörü",
               "cause": "Olası nedenler: RAID denetleyici önbellek bataryası veya sistem bataryasının zayıflaması/ömrünün dolması.",
               "impact": "Denetleyici yazma önbelleğini kapatabilir (disk performansı düşer).",
               "steps": ["Hangi bataryanın (denetleyici/sistem) alarm verdiğini BMC/yönetim kartı günlüğünden belirleyin.",
                         "Donanım desteğiyle batarya değişimi planlayın."]},
        "en": {"title": "Battery sensor",
               "cause": "Possible causes: RAID controller cache battery or system battery weakening/end of life.",
               "impact": "The controller may disable write cache (lower disk performance).",
               "steps": ["Identify which battery (controller/system) is alarming from the BMC/management controller log.",
                         "Plan a battery replacement with hardware support."]},
    },
    "memory": {
        "tr": {"title": "Bellek (DIMM) sensörü",
               "cause": "Olası nedenler: düzeltilebilir/düzeltilemez bellek hataları, arızalı DIMM.",
               "impact": "Düzeltilemez hatalarda host beklenmedik şekilde yeniden başlayabilir.",
               "steps": ["BMC/yönetim kartı günlüğünde hangi DIMM yuvasının hata verdiğini belirleyin.",
                         "Hata tekrarlıyorsa donanım desteğiyle DIMM değişimi planlayın."]},
        "en": {"title": "Memory (DIMM) sensor",
               "cause": "Possible causes: correctable/uncorrectable memory errors, faulty DIMM.",
               "impact": "Uncorrectable errors may cause an unexpected host restart.",
               "steps": ["Identify which DIMM slot reports errors in the BMC/management controller log.",
                         "If errors repeat, plan a DIMM replacement with hardware support."]},
    },
    "processor": {
        "tr": {"title": "İşlemci sensörü",
               "cause": "Olası nedenler: işlemci hatası veya aşırı ısınma/kısıtlama.",
               "impact": "Performans düşüşü veya beklenmedik yeniden başlatma riski.",
               "steps": ["BMC/yönetim kartı günlüğünde işlemci olaylarını ve sıcaklık/fan alarmlarını birlikte kontrol edin.",
                         "Tekrarlıyorsa donanım desteğine açın."]},
        "en": {"title": "Processor sensor",
               "cause": "Possible causes: processor fault or overheating/throttling.",
               "impact": "Risk of performance loss or unexpected restart.",
               "steps": ["Check processor events together with temperature/fan alarms in the BMC/management controller log.",
                         "Open a hardware support case if it repeats."]},
    },
    "generic": {
        "tr": {"title": "Donanım sensörü",
               "cause": "Sensör türü kaynakta belirtilmemiş; kök neden yalnız bu bilgiden çıkarılamaz.",
               "impact": "Etki sensörün türüne bağlıdır.",
               "steps": ["Alarm veren sensörün adını BMC/yönetim kartı günlüğünde bulup türünü ve zamanını doğrulayın.",
                         "Sorun sürüyorsa donanım desteğine açın."]},
        "en": {"title": "Hardware sensor",
               "cause": "The sensor type is not reported by the source; the root cause cannot be derived from this information alone.",
               "impact": "Impact depends on the sensor type.",
               "steps": ["Find the alarming sensor by name in the BMC/management controller log and confirm its type and time.",
                         "Open a hardware support case if it persists."]},
    },
}


def _guide_key(sensor: Dict[str, Any]) -> str:
    text = f"{sensor.get('type') or ''}".lower()
    for needle, key in _TYPE_KEYS:
        if needle in text:
            return key
    return "generic"


def _sensors(ev: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ev = ev or {}
    for k in ("sensors", "bad_sensors", "current_sensors"):
        v = ev.get(k)
        if isinstance(v, list) and v:
            return [s for s in v if isinstance(s, dict)]
    return []


def sensor_guides(row: InfraFinding, locale: str = "tr") -> Optional[Dict[str, Any]]:
    """Sensör kaynaklı donanım bulguları için tür başına genel rehber. Diğer bulgularda None."""
    if row.check_id not in _SENSOR_CHECKS or row.result != "fail":
        return None
    sensors = _sensors(row.evidence)
    lang = "en" if locale == "en" else "tr"
    keys: List[str] = []
    for s in sensors:
        k = _guide_key(s)
        if k not in keys:
            keys.append(k)
    if not keys:
        keys = ["generic"]
    ev = row.evidence or {}
    vendor = ev.get("vendor")
    return {
        "kind": "rule_guide",
        "guides": [{"key": k, **_GUIDES[k][lang]} for k in keys],
        "vendor": vendor,
        # Satıcı KB bağlantıları: yalnız doğrulanmış resmî kaynaklardan. Donanım satıcıları için doğrulanmış kayıt yok.
        "official_links": [{"id": x.get("id"), "title_tr": x.get("title_tr"), "title_en": x.get("title_en"), "url": x.get("url")}
                           for x in reference_sources.verified_sources("hardware_vendor")],
    }


def related_findings(db: Session, row: InfraFinding, limit: int = 30) -> List[Dict[str, Any]]:
    """Aynı varlıkta (host) açık, başarısız diğer bulgular — tek olay gibi okunsun diye."""
    q = (db.query(InfraFinding)
         .filter(InfraFinding.platform == row.platform, InfraFinding.source_id == row.source_id,
                 InfraFinding.entity_ref == row.entity_ref, InfraFinding.active.is_(True),
                 InfraFinding.result == "fail", InfraFinding.id != row.id))
    items = sorted(q.all(), key=lambda r: (_SEV_ORDER.get(r.severity, 9), r.check_id))
    return [{"id": r.id, "check_id": r.check_id, "category": r.category, "severity": r.severity,
             "title": r.title, "detail": r.detail} for r in items[:limit]]


def host_impact(db: Session, row: InfraFinding) -> Optional[Dict[str, Any]]:
    """Bu host kapanırsa VM'ler kalan host'lara sığar mı? (virt_capacity_planner.host_failure — aynı hesap.)"""
    if row.entity_kind != "host" or row.source_id is None:
        return None
    from app.services.virt_capacity_planner import host_failure
    label = cap_hier.cluster_label(row.cluster_name, row.entity_name)
    res = host_failure(db, hypervisor_id=row.source_id, cluster=label, hosts=[row.entity_name])
    if not res.get("ok"):
        return {"available": False, "reason": res.get("error")}
    return {
        "available": True, "cluster": label, "hypervisor_id": row.source_id, "host": row.entity_name, "verdict": res["overall"]["verdict"], "status": res["overall"]["status"],
        "limiting": res["overall"]["limiting"],
        "vms": res["displaced"]["count"], "memory_gb": res["displaced"]["memory_gb"],
        "unplaced": len(res["unplaced"]), "remaining_hosts": len(res["remaining_hosts"]),
        "after_memory_pct": (res.get("after") or {}).get("memory_pct"), "threshold_pct": res.get("threshold_pct"),
        "confidence": res.get("confidence"), "notes": res.get("notes", [])[:3],
    }


def event_groups(db: Session, row: InfraFinding) -> Dict[str, Any]:
    """(a) aynı olay (aynı kök) ve (b) aynı host'taki diğer açık bulgular — `findings/events.py` kural eşlemesiyle."""
    from app.services.findings import events as ev
    sp = ev.event_split(db, row)
    return {
        "event": {"key": sp["key"], "family": sp["family"], "member_ids": [m.id for m in sp["members"]],
                  "representative_id": sp["representative_id"]},
        "related_event": [ev.brief(m) for m in sp["members"] if m.id != row.id][:30],
        "related_other": [ev.brief(o) for o in sp["others"]][:30],
    }


def finding_context(db: Session, row: InfraFinding, locale: str = "tr") -> Dict[str, Any]:
    out = {
        "finding_id": row.id,
        "guide": sensor_guides(row, locale),
        # Geriye dönük uyumlu: aynı host'taki TÜM açık bulgular. Ayrım için `related_event` / `related_other`.
        "related": related_findings(db, row) if row.entity_kind == "host" else [],
        "impact": host_impact(db, row) if row.result == "fail" and row.category == "hardware" else None,
    }
    if row.entity_kind == "host":
        out.update(event_groups(db, row))
    return out
