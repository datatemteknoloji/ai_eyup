"""Gerçek bir VBR'den SALT-OKUNUR fixture toplar (F.4).

Kullanım (ainew backend konteynerinde veya PYTHONPATH=backend ile):

  VBR_PASSWORD='…' python backend/scripts/veeam_collect_fixtures.py \\
      --host vbr.example.local --user svc-ainew --revision 1.3-rev1 [--no-verify | --ca-bundle ca.pem] \\
      [--version 13.0.1.180] [--out backend/app/tests/fixtures/veeam] [--mask-names] [--dry-run]

Güvenlik:
  * Yalnız GET (token/logout hariç) — ``VeeamRestClient`` yazma uçlarını reddeder; bu script ek endpoint eklemez.
  * Parola yalnız ortam değişkeninden (``--password-env``, varsayılan VBR_PASSWORD) veya etkileşimli istemden gelir;
    komut satırı argümanı olarak ALINMAZ (shell geçmişine/ps çıktısına sızmasın).
  * Çıktı maskelenir (``fixture_mask``): host adı, IP, kullanıcı adı, yol. Maskelenmeden SONRA kalan olası sızıntı varsa
    dosya YAZILMAZ (``--allow-leaks`` ile geçilir; önerilmez).
  * ``--dry-run``: hiçbir şey yazmaz; endpoint durumlarını ve maskeleme istatistiğini yazdırır.

Çıktı: ``<out>/<version>/<endpoint_key>.json`` + ``_manifest.json`` (source=real, masked=true). Sürüm, serverInfo
(yalnız Backup Administrator) ile bulunur; yetki yoksa ``--version`` verilmelidir. Paylaşmadan önce dosyaları gözle kontrol edin.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.services.backup.fixture_mask import Masker, leaks
from app.services.backup.veeam_api_ref import DEFAULT_REVISION, ENDPOINTS, REVISIONS
from app.services.backup.veeam_client import VeeamApiError, VeeamRestClient

SKIP = {"token", "logout"}


def _params(key: str, limit: int) -> Dict[str, Any]:
    p: Dict[str, Any] = {"limit": limit, "skip": 0}
    if key == "sessions":
        p.update(typeFilter="BackupJob", orderColumn="CreationTime", orderAsc="false",
                 createdAfterFilter=(datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    elif key in ("restore_points", "backup_objects"):
        p["platformNameFilter"] = "VMware"
        if key == "restore_points":
            p.update(orderColumn="CreationTime", orderAsc="false")
    return p


def collect(client: VeeamRestClient, limit: int) -> Dict[str, Dict[str, Any]]:
    """→ {key: {"status": ok|forbidden|error, "body": …}} — yalnız GET."""
    out: Dict[str, Dict[str, Any]] = {}
    first_obj: Optional[str] = None
    for key, ep in ENDPOINTS.items():
        if key in SKIP or ep.method != "GET":
            continue
        try:
            if "{" in ep.path:
                if key != "object_restore_points" or not first_obj:
                    out[key] = {"status": "skipped", "body": None}
                    continue
                body = client.get_json(key, {"limit": min(limit, 5), "orderColumn": "CreationTime", "orderAsc": "false"},
                                       path={"id": first_obj})
            elif key in ("server_info", "server_time"):
                body = client.get_json(key)
            else:
                body = client.get_json(key, _params(key, limit))
        except VeeamApiError as e:
            if e.kind in ("auth", "network", "tls"):
                raise
            out[key] = {"status": "forbidden" if e.kind == "forbidden" else "error", "body": None, "http": e.status}
            continue
        out[key] = {"status": "ok", "body": body}
        if key == "backup_objects":
            for o in (body.get("data") or []):
                if isinstance(o, dict) and (o.get("restorePointsCount") or 0) > 0:
                    first_obj = str(o.get("id"))
                    break
    return out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=9419)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password-env", default="VBR_PASSWORD")
    ap.add_argument("--revision", default=DEFAULT_REVISION, choices=sorted(REVISIONS))
    ap.add_argument("--ca-bundle")
    ap.add_argument("--no-verify", action="store_true", help="TLS doğrulamasını kapatır (önerilmez)")
    ap.add_argument("--version", help="Çıktı klasör adı (varsayılan: serverInfo.buildVersion)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "veeam"))
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--mask-names", action="store_true", help="'name' alanlarını da maskele (VM/iş/depo adları)")
    ap.add_argument("--allow-leaks", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    pw = os.environ.get(a.password_env) or getpass.getpass(f"{a.user} parolası: ")
    verify: Any = a.ca_bundle or (not a.no_verify)
    client = VeeamRestClient(a.host, a.user, pw, port=a.port, verify=verify, revision=a.revision)
    try:
        raw = collect(client, max(1, min(a.limit, 200)))
    finally:
        client.logout()

    masker = Masker(mask_names=a.mask_names)
    masked: Dict[str, Any] = {k: masker.mask(v["body"]) for k, v in raw.items() if v["status"] == "ok"}
    found = leaks(masked)
    version = a.version
    if not version:
        si = (raw.get("server_info") or {}).get("body") or {}
        version = str(si.get("buildVersion") or "").strip() or None
    status = {k: {"status": v["status"], **({"http": v["http"]} if v.get("http") else {}),
                  **({"rows": len((v["body"] or {}).get("data") or [])} if v["status"] == "ok" and isinstance(v["body"], dict) and "data" in v["body"] else {})}
              for k, v in raw.items()}
    print(json.dumps({"version": version, "revision": a.revision, "endpoints": status,
                      "mask": masker.mapping_sizes(), "leaks": found}, ensure_ascii=False, indent=1))
    if found and not a.allow_leaks:
        print("\nSızıntı olasılığı var — dosya YAZILMADI. Maskelemeyi gözden geçirin veya --allow-leaks kullanın.", file=sys.stderr)
        return 2
    if a.dry_run:
        print("\n--dry-run: dosya yazılmadı.")
        return 0
    if not version:
        print("\nSürüm bulunamadı (serverInfo yetkisiz). --version verin.", file=sys.stderr)
        return 3
    d = Path(a.out) / version
    d.mkdir(parents=True, exist_ok=True)
    for k, body in masked.items():
        (d / f"{k}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    manifest = {"source": "real", "masked": True, "version": version, "revision": a.revision,
                "collected_at": datetime.now(timezone.utc).isoformat(), "endpoints": status,
                "mask_names": bool(a.mask_names), "note": "Gerçek VBR yanıtı (maskeli). Paylaşmadan önce gözle kontrol edin."}
    (d / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nYazıldı: {d}  ({len(masked)} endpoint)")
    return 0
