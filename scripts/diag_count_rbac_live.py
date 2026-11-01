"""Sayım kuralı RBAC canlı kontrolü — DB'ye YAZMAZ (kullanıcı oturumu/giriş kaydı oluşturmaz).

Operatör kullanıcıları için uygulamanın kendi `create_access_token`ı ile süreç içinde (jti'li, oturum kaydı
OLMAYAN) kısa ömürlü token üretir; unified sohbet uç noktasına sorar. Sohbet oturumu açılır (normal sohbet
davranışı) ve sonunda silinir.

  docker cp scripts/diag_count_rbac_live.py server_management_backend:/tmp/
  docker exec -w /app -e PYTHONPATH=/app server_management_backend python /tmp/diag_count_rbac_live.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.module import UserModule
from app.models.user import User

BASE = "http://127.0.0.1:8000/api/v1"

# (kullanıcı, soru, kural cevabı beklenir mi, cevapta bulunmaması gereken kalıp)
CASES = [
    ("virtualization_user", "Kaç VM var?", True, None),
    ("virtualization_user", "OpenShift'te kaç node var?", False, r"Toplam node: \d+|ZZ-FAKE-OCP \| 15"),
    ("openshift_user", "OpenShift'te kaç node var?", True, None),
    ("openshift_user", "Kaç VM var?", False, r"Toplam VM: \d+|ZZ-FAKE-vCenter \| 1000"),
    ("linux_user", "Kaç VM var?", False, r"Toplam VM: \d+|ZZ-FAKE-vCenter \| 1000"),
    ("linux_user", "OpenShift'te kaç proje var?", False, r"Toplam proje|ZZ-FAKE-OCP \| 13"),
    ("virtualization_user", "Kaç cluster var?", True, r"OpenShift cluster sayısı"),   # yalnız sanallaştırma grubu
]


def ask(token: str, msg: str, limit_s: float = 25.0):
    req = urllib.request.Request(BASE + "/unified-chat/stream", data=json.dumps({"message": msg}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST")
    ans, sid, t0 = "", None, time.time()
    try:
        with urllib.request.urlopen(req, timeout=limit_s) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    d = json.loads(line[5:].strip())
                except Exception:
                    continue
                sid = d.get("session_id") or sid
                ans += d.get("token") or ""
                if d.get("done") or time.time() - t0 > limit_s:
                    break
    except Exception as e:  # zaman aşımı: kısmi cevapla devam
        ans += f"\n[kesildi: {type(e).__name__}]"
    return ans, sid, round(time.time() - t0, 2)


def main() -> int:
    db = SessionLocal()
    out, bad = [], 0
    try:
        for uname, q, expect_rule, forbid in CASES:
            u = db.query(User).filter(User.username == uname).first()
            if not u:
                out.append(f"- {uname}: kullanıcı yok (ATLANDI)")
                continue
            mods = sorted(m for (m,) in db.query(UserModule.module_id).filter(UserModule.user_id == u.id).all())
            tok = create_access_token(u.username, extra={"uid": u.id, "role": u.role})
            ans, sid, dt = ask(tok, q)
            rule = bool(re.search(r"Kaynak: envanter veritabanı", ans))
            leak = bool(forbid and re.search(forbid, ans))
            ok = (rule == expect_rule) and not leak
            bad += 0 if ok else 1
            out.append(f"| {uname} | {','.join(mods)} | {q} | kural={'evet' if rule else 'hayır'} (beklenen {'evet' if expect_rule else 'hayır'}) | "
                       f"sızıntı={'VAR' if leak else 'yok'} | {dt}s | {'GEÇTİ' if ok else 'KALDI'} |")
            if sid:
                try:
                    urllib.request.urlopen(urllib.request.Request(BASE + f"/unified-chat/sessions/{sid}",
                                           headers={"Authorization": f"Bearer {tok}"}, method="DELETE"), timeout=15)
                except Exception:
                    pass
            snippet = re.sub(r"\s+", " ", ans)[:160]
            out.append(f"  - cevap: {snippet}")
    finally:
        db.close()
    print("| kullanıcı | modüller | soru | kural | sızıntı | süre | sonuç |\n|---|---|---|---|---|---|---|")
    print("\n".join(out))
    print(f"\nKALAN: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
