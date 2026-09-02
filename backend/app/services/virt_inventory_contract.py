"""Virt envanter sözleşmesi — sınıf bazlı (tek soruya yama değil).

Amaç: VM disk / datastore / ESX özet gibi SoT sorularında
  1) Doğru db_* tool verisinin garanti çekilmesi (prefetch)
  2) Cevabın tool JSON'undan üretilmesi (model 'eksik/uydurma' yazamasın)
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ── Niyet sınıfları ──────────────────────────────────────────────────────────
KIND_VM_DISK = "vm_disk"
KIND_DATASTORE = "datastore"
KIND_ESX_HOST = "esx_host"
KIND_VM_LIST = "vm_list"

_VM_RE = re.compile(
    r"(?<![a-z0-9_])vm(?:s|ler|leri|lerin|lerde|lerdeki|ye|yi|nin|nın|nün|'s|’s)?(?![a-z0-9_])"
    r"|sanal\s*makine|virtual\s*machine",
    re.I,
)


def detect_virt_inventory_kind(message: str) -> Optional[str]:
    """Soru virt DB envanter sınıfına giriyor mu? (perf/QueryPerf hariç)."""
    m = (message or "").lower()
    if not m.strip():
        return None

    # Canlı perf — bu sözleşme dışı (vcenter_perf_query)
    if any(k in m for k in ("disk rate", "disk requests", "iops", "queryperf", "kbps")):
        if not any(k in m for k in ("adet", "boyut", "capacity_gb", "vmdk", "kapasite")):
            return None

    if any(k in m for k in ("datastore", "datastores", "ds doluluk", "datastore doluluk")):
        return KIND_DATASTORE

    if any(k in m for k in ("esxi host", "esx host", "host list", "host özet", "host ozet")):
        if "vm" not in m and not _VM_RE.search(m):
            return KIND_ESX_HOST

    diskish = any(
        k in m
        for k in (
            "disk", "disks", "vmdk", "disk_gb", "disk boyutu", "disk boyut",
            "disk adet", "disk sayısı", "disk sayisi", "her bir disk",
            "hard disk", "storage_gb", "provisioned",
        )
    )
    if diskish and (_VM_RE.search(m) or "sanal" in m or "vcenter" in m or "vmware" in m):
        return KIND_VM_DISK

    # "tüm vm'ler" / poweredOn listesi
    if _VM_RE.search(m) and any(
        k in m for k in ("liste", "list", "kaç", "kac", "özet", "ozet", "hepsi", "tüm", "tum", "table", "/table")
    ):
        if diskish:
            return KIND_VM_DISK
        return KIND_VM_LIST

    if diskish and any(k in m for k in ("vcenter", "esxi", "esx", "hypervisor", "sanallaş", "sanallas")):
        return KIND_VM_DISK

    return None


def inventory_system_addendum(kind: str) -> str:
    """Tool-loop system ek — prefetch yanında modele de hatırlatma."""
    common = (
        "\n\nVIRT ENVANTER SÖZLEŞMESİ (zorunlu):\n"
        "- Cevabı YALNIZ db_* tool JSON satırlarından kur; RAG/tahmin yok.\n"
        "- Tool'da disk_gb/disk_count doluysa ASLA 'toplanmadı/eksik/bilinmiyor' yazma.\n"
        "- disk_gb null olan satır için 'DB null (sync enrichment gerekir)' de.\n"
        "- Kullanıcı /table veya tablo istediyse markdown tablo üret.\n"
    )
    if kind == KIND_VM_DISK:
        return common + (
            "- VM disk sorusu: db_list_vms (disk_gb, disk_count, disks zorunlu alanlar). "
            "Tek tek db_vm_detail döngüsü YAPMA — liste zaten disks[] içerir.\n"
            "- Her VM için: adet=disk_count, toplam=disk_gb, kırılım=disks[].label/capacity_gb.\n"
        )
    if kind == KIND_DATASTORE:
        return common + "- Datastore: db_list_datastores (capacity/free/usage).\n"
    if kind == KIND_ESX_HOST:
        return common + "- ESXi host: db_list_esx_hosts (fields ile istenen kolonlar).\n"
    if kind == KIND_VM_LIST:
        return common + "- VM listesi: db_list_vms (name, ip, power_state, host, disk_gb).\n"
    return common


def _disk_count(disks: Any, disk_gb: Any) -> Optional[int]:
    if isinstance(disks, list):
        return len(disks)
    if disk_gb is None:
        return None
    return None


def enrich_vm_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Satıra disk_count ekle (yoksa disks uzunluğundan)."""
    out = dict(row)
    disks = out.get("disks")
    if out.get("disk_count") is None:
        n = _disk_count(disks, out.get("disk_gb"))
        if n is not None:
            out["disk_count"] = n
    return out


def format_vm_disk_table(vms: Sequence[Dict[str, Any]], *, as_of: Optional[str] = None) -> str:
    """Tool satırlarından deterministik VM disk tablosu."""
    lines = [
        "## VM Disk Envanteri (kaynak: db_list_vms)",
        "",
        "| VM Adı | IP | Disk Adedi | Toplam (GB) | Diskler (label: GB) |",
        "|---|---|---:|---:|---|",
    ]
    filled = 0
    empty = 0
    for raw in vms:
        v = enrich_vm_row(raw if isinstance(raw, dict) else {})
        name = v.get("name") or "—"
        ip = v.get("ip") or "—"
        dgb = v.get("disk_gb")
        dcnt = v.get("disk_count")
        disks = v.get("disks") if isinstance(v.get("disks"), list) else []
        if dcnt is None and disks:
            dcnt = len(disks)
        if dgb is None and not disks:
            empty += 1
            parts = "DB null"
            dcnt_s = "—"
            dgb_s = "—"
        else:
            filled += 1
            dcnt_s = str(dcnt if dcnt is not None else (len(disks) if disks else "—"))
            dgb_s = str(dgb if dgb is not None else "—")
            if disks:
                parts = "; ".join(
                    f"{(d.get('label') or 'disk')}: {d.get('capacity_gb', '?')}"
                    for d in disks
                    if isinstance(d, dict)
                ) or "—"
            else:
                parts = "—"
        lines.append(f"| {name} | {ip} | {dcnt_s} | {dgb_s} | {parts} |")

    lines.extend([
        "",
        f"**Özet:** {len(vms)} VM — disk_gb dolu: {filled}, DB null: {empty}.",
    ])
    if as_of:
        lines.append(f"as_of: `{as_of}`")
    lines.append(
        "_Not: Adet/boyut vCenter provisioned disk envanteridir (guest `df` değil)._"
    )
    return "\n".join(lines)


def format_datastore_table(rows: Sequence[Dict[str, Any]], *, as_of: Optional[str] = None) -> str:
    lines = [
        "## Datastore Envanteri (kaynak: db_list_datastores)",
        "",
        "| Datastore | Kapasite (GB) | Boş (GB) | Kullanım % | vCenter |",
        "|---|---:|---:|---:|---|",
    ]
    for r in rows:
        if not isinstance(r, dict):
            continue
        lines.append(
            f"| {r.get('name') or '—'} | {r.get('capacity_gb', '—')} | "
            f"{r.get('free_gb', '—')} | {r.get('usage_pct', '—')} | {r.get('hypervisor') or '—'} |"
        )
    if as_of:
        lines.extend(["", f"as_of: `{as_of}`"])
    return "\n".join(lines)


def format_esx_host_table(rows: Sequence[Dict[str, Any]], *, as_of: Optional[str] = None) -> str:
    lines = [
        "## ESXi Host Envanteri (kaynak: db_list_esx_hosts)",
        "",
        "| Host | IP | Version | CPU % | Mem % | Durum |",
        "|---|---|---|---:|---:|---|",
    ]
    for r in rows:
        if not isinstance(r, dict):
            continue
        lines.append(
            f"| {r.get('name') or '—'} | {r.get('ip') or '—'} | {r.get('version') or '—'} | "
            f"{r.get('cpu_pct', '—')} | {r.get('mem_pct', '—')} | "
            f"{r.get('connection_state') or '—'} |"
        )
    if as_of:
        lines.extend(["", f"as_of: `{as_of}`"])
    return "\n".join(lines)


def format_vm_list_table(vms: Sequence[Dict[str, Any]], *, as_of: Optional[str] = None) -> str:
    lines = [
        "## VM Listesi (kaynak: db_list_vms)",
        "",
        "| VM Adı | IP | Power | ESXi host | Disk (GB) | vCPU | RAM (MB) |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for v in vms:
        if not isinstance(v, dict):
            continue
        lines.append(
            f"| {v.get('name') or '—'} | {v.get('ip') or '—'} | {v.get('power_state') or '—'} | "
            f"{v.get('host') or v.get('esxi_host') or '—'} | {v.get('disk_gb', '—')} | "
            f"{v.get('vcpu', '—')} | {v.get('memory_mb', '—')} |"
        )
    lines.extend(["", f"**Toplam:** {len(vms)} VM"])
    if as_of:
        lines.append(f"as_of: `{as_of}`")
    return "\n".join(lines)


def materialize_from_tool_results(
    kind: str,
    tool_results: Sequence[Dict[str, Any]],
) -> Optional[str]:
    """Prefetch/tool sonuçlarından deterministik cevap. Yoksa None."""
    by_name: Dict[str, Any] = {}
    for tr in tool_results:
        if not isinstance(tr, dict):
            continue
        name = tr.get("tool") or tr.get("name")
        payload = tr.get("result")
        if name and payload is not None:
            by_name[str(name)] = payload

    if kind in (KIND_VM_DISK, KIND_VM_LIST):
        payload = by_name.get("db_list_vms")
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        vms = payload.get("vms") or []
        if not isinstance(vms, list):
            return None
        as_of = payload.get("as_of")
        if kind == KIND_VM_DISK:
            return format_vm_disk_table(vms, as_of=as_of)
        return format_vm_list_table(vms, as_of=as_of)

    if kind == KIND_DATASTORE:
        payload = by_name.get("db_list_datastores")
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        rows = payload.get("datastores") or payload.get("items") or []
        if not isinstance(rows, list):
            return None
        return format_datastore_table(rows, as_of=payload.get("as_of"))

    if kind == KIND_ESX_HOST:
        payload = by_name.get("db_list_esx_hosts")
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        rows = payload.get("hosts") or payload.get("items") or []
        if not isinstance(rows, list):
            return None
        return format_esx_host_table(rows, as_of=payload.get("as_of"))

    return None


def prefetch_spec(kind: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(tool_name, args) — loop başında zorunlu çekim."""
    if kind in (KIND_VM_DISK, KIND_VM_LIST):
        return (
            "db_list_vms",
            {
                "limit": 500,
                "include_disks": True,
                "fields": [
                    "name", "ip", "power_state", "host", "cluster", "datastore",
                    "hypervisor", "vcpu", "memory_mb", "disk_gb", "disk_count", "disks",
                ],
            },
        )
    if kind == KIND_DATASTORE:
        return ("db_list_datastores", {"limit": 200})
    if kind == KIND_ESX_HOST:
        return (
            "db_list_esx_hosts",
            {
                "fields": [
                    "name", "ip", "version", "cpu_pct", "mem_pct",
                    "connection_state", "hypervisor",
                ],
            },
        )
    return None


def parse_tool_payloads_from_text(tool_text: str) -> List[Dict[str, Any]]:
    """Eski final.tool_text'ten kurtarma (JSON blokları)."""
    out: List[Dict[str, Any]] = []
    if not tool_text:
        return out
    # [label]\n{json} kalıbı
    parts = re.split(r"\n(?=\[)", tool_text)
    for part in parts:
        part = part.strip()
        if not part.startswith("["):
            continue
        nl = part.find("\n")
        if nl < 0:
            continue
        body = part[nl + 1 :].strip()
        if not body.startswith("{"):
            continue
        try:
            payload = json.loads(body)
        except Exception:
            continue
        label = part[1:part.find("]")].strip().lower()
        tool = None
        if "db_list_vms" in label or "vm listesi" in label:
            tool = "db_list_vms"
        elif "datastore" in label:
            tool = "db_list_datastores"
        elif "esxi" in label or "esx" in label:
            tool = "db_list_esx_hosts"
        if tool:
            out.append({"tool": tool, "result": payload})
    return out
