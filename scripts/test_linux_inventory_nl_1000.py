#!/usr/bin/env python3
"""
Linux NL envanter + direkt-komut niyet testi (1000 soru).

Önceki linux-admin-1000 suite collect+LLM yolundaydı; chat stream'deki
direkt-komut bypass'ı ve filo hostname/IP sorularını kapsamıyordu.
Bu suite o boşluğu kapatır — LLM çağırmaz, deterministik intent testidir.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.linux_chat_intent import (  # noqa: E402
    extract_direct_commands,
    format_fleet_inventory_answer,
    is_fleet_inventory_query,
)

OUT = Path("/tmp/linux-inventory-nl-1000-results.json")
QUESTIONS_OUT = Path("/tmp/linux-inventory-nl-1000-questions.json")


def _variants(base: str) -> list[str]:
    prefixes = ["", "Admin: ", "Acil: ", "Lütfen ", "Haftalık kontrol: ", "Bilgi: "]
    suffixes = ["", "?", " nedir?", " ver", " verir misin", " göster", " listele", " alabilir miyim"]
    out = []
    for p in prefixes:
        for s in suffixes:
            out.append(f"{p}{base}{s}".strip())
    return out


def build_questions() -> list[dict]:
    """1000 soru: inventory / no_cmd / real_cmd kategorileri."""
    inv_bases = [
        "linux sunucularımızın hostname ve ip bilgisini",
        "sunucuların hostname ve ip adresi",
        "hostname ve ip bilgisi",
        "ip bilgisini ver",
        "sunucu listesi",
        "hangi sunucularımız var",
        "tüm sunucuların ip adresleri",
        "ai ready sunucu listesi",
        "sunucu envanteri",
        "makine adı ve ip",
        "fqdn ve ip bilgisi",
        "sunucularımızın isim ve ip",
        "linux hostların hostname ip",
        "envanter ver hostname ip",
        "sunucuların adlarını ve ip'lerini",
        "bütün sunucular hostname ip",
        "sunucu hostname ip tablosu",
        "linux sunucu ip listesi",
        "host adı ve ip adresi listesi",
        "sunucularımızın ip bilgisi",
        "hangi linux sunucular kayıtlı",
        "kayıtlı sunucu hostname ip",
        "inventory hostname and ip",
        "list servers hostname ip",
        "server inventory with ip",
    ]
    # Gerçek komut — extract edilmeli, inventory False
    cmd_bases = [
        "ip addr",
        "ip -br a",
        "ip route",
        "ip link show",
        "free -h",
        "df -h",
        "ss -tulnp",
        "uptime",
        "vmstat 1 5",
        "iostat -xz 1 3",
        "lscpu",
        "lsblk",
        "netstat -tulnp",
        "ifconfig -a",
        "arp -n",
        "top -b -n 1",
        "ps aux",
        "route -n",
    ]
    # Ne inventory ne komut (veya tek sunucu OS sorusu — inventory False kabul)
    other_bases = [
        "selinux durumu nedir",
        "firewalld aktif mi",
        "kernel sürümü",
        "disk doluluk",
        "cpu kullanımı",
        "minio2 hostname nedir",
        "swap ne kadar",
        "dmesg hataları",
        "os release",
        "uptime kaç gün",
    ]

    inv_qs: list[dict] = []
    for b in inv_bases:
        for v in _variants(b):
            inv_qs.append({"q": v, "expect": "inventory", "base": b})
    cmd_qs: list[dict] = []
    for b in cmd_bases:
        for v in _variants(b):
            cmd_qs.append({"q": v, "expect": "command", "base": b, "cmd_prefix": b.split()[0]})
    other_qs: list[dict] = []
    for b in other_bases:
        for v in _variants(b):
            other_qs.append({"q": v, "expect": "neither", "base": b})

    # Dengeli 1000: ~550 inventory / ~300 command / ~150 neither
    qs = inv_qs[:550] + cmd_qs[:300] + other_qs[:150]
    i = 0
    while len(qs) < 1000:
        b = inv_bases[i % len(inv_bases)]
        qs.append({"q": f"Tekrar {i}: {b} lütfen", "expect": "inventory", "base": b})
        i += 1
    return qs[:1000]


class _S:
    def __init__(self, name, hostname, ip, os_version="RHEL 9", status="online"):
        self.name = name
        self.hostname = hostname
        self.ip_address = ip
        self.os_version = os_version
        self.status = status
        self.vm_guest_hostname = None
        self.os_type = "Linux"


def score(item: dict) -> dict:
    q = item["q"]
    expect = item["expect"]
    cmds = extract_direct_commands(q)
    inv = is_fleet_inventory_query(q)
    ok = False
    reason = ""
    if expect == "inventory":
        ok = inv is True and cmds == []
        reason = "inv+no_cmd" if ok else f"inv={inv} cmds={cmds}"
        # Kritik: Usage tetikleyen çıplak ip olmamalı
        if any(c.strip() == "ip" for c in cmds):
            ok = False
            reason = "BARE_IP"
    elif expect == "command":
        prefix = item.get("cmd_prefix") or item["base"].split()[0]
        ok = (not inv) and any(c.split()[0] == prefix for c in cmds)
        # ip için en az 2 token
        if prefix == "ip":
            ok = ok and any(len(c.split()) >= 2 for c in cmds)
        reason = f"cmds={cmds}" if ok else f"inv={inv} cmds={cmds}"
    else:  # neither
        ok = (not inv) and ("ip" not in [c.strip() for c in cmds])
        # free/df tek başına other'da yok; bare ip yasak
        if any(c.strip() == "ip" for c in cmds):
            ok = False
            reason = "BARE_IP"
        else:
            reason = f"inv={inv} cmds={cmds}"
    return {
        "q": q,
        "expect": expect,
        "ok": ok,
        "inventory": inv,
        "cmds": cmds,
        "reason": reason,
    }


def main() -> int:
    t0 = time.time()
    qs = build_questions()
    QUESTIONS_OUT.write_text(json.dumps([x["q"] for x in qs], ensure_ascii=False, indent=0), encoding="utf-8")

    results = [score(x) for x in qs]
    fails = [r for r in results if not r["ok"]]
    by_exp = {}
    for r in results:
        by_exp.setdefault(r["expect"], {"pass": 0, "fail": 0})
        by_exp[r["expect"]]["pass" if r["ok"] else "fail"] += 1

    # format smoke
    table = format_fleet_inventory_answer([
        _S("minio2", "minio2.datatem.local", "192.168.1.50"),
        _S("rhelcluster01", "rhelcluster01", "192.168.1.10"),
    ])
    fmt_ok = "minio2" in table and "192.168.1.50" in table and "Hostname" in table

    summary = {
        "n": len(results),
        "pass": len(results) - len(fails),
        "fail": len(fails),
        "pass_rate_pct": round(100.0 * (len(results) - len(fails)) / len(results), 2),
        "by_expect": by_exp,
        "format_ok": fmt_ok,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "fails_sample": fails[:40],
    }
    OUT.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"-> {OUT}")
    return 0 if summary["fail"] == 0 and fmt_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
