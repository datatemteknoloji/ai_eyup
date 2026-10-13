#!/usr/bin/env bash
# Automic (UC4) modülü teşhis betiği — salt okunur; sır yazdırmaz.
#
# Kullanım: scripts/automic-diagnose.sh [--backend <container>] [--db <container>]
# Kontroller: modül DB konteyneri, backend sürücüsü (oracledb), modül DB şeması,
# kayıtlı sistemler (bağlantı bilgisi şifresiz), kaynağa TCP erişimi, collector durumu.
set -u

BACKEND="${AUTOMIC_BACKEND_CONTAINER:-server_management_backend}"
DBC="${AUTOMIC_DB_CONTAINER:-automic_db}"
while [ $# -gt 0 ]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2 ;;
    --db) DBC="$2"; shift 2 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Bilinmeyen argüman: $1" >&2; exit 2 ;;
  esac
done

ok()   { printf '  [OK]   %s\n' "$*"; }
warn() { printf '  [UYARI] %s\n' "$*"; }
fail() { printf '  [HATA] %s\n' "$*"; FAILED=1; }
FAILED=0

command -v docker >/dev/null 2>&1 || { echo "docker bulunamadı" >&2; exit 2; }

echo "== Modül DB ($DBC)"
if [ "$(docker inspect -f '{{.State.Running}}' "$DBC" 2>/dev/null)" = "true" ]; then
  ok "konteyner çalışıyor ($(docker inspect -f '{{.Config.Image}}' "$DBC"))"
  if docker exec "$DBC" sh -c 'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    ok "pg_isready"
  else
    fail "pg_isready başarısız"
  fi
else
  fail "konteyner çalışmıyor — docker compose up -d automic-db"
fi

echo "== Backend ($BACKEND)"
if [ "$(docker inspect -f '{{.State.Running}}' "$BACKEND" 2>/dev/null)" != "true" ]; then
  fail "backend konteyneri çalışmıyor"
  exit 1
fi
ok "konteyner çalışıyor"

docker exec -i "$BACKEND" python - <<'PY'
import os, socket, sys

def ok(m): print(f"  [OK]   {m}")
def warn(m): print(f"  [UYARI] {m}")
BAD = []
def fail(m): BAD.append(m); print(f"  [HATA] {m}")

try:
    import oracledb
    ok(f"python-oracledb {oracledb.__version__}")
except Exception:
    fail("python-oracledb kurulu değil — backend imajını yeniden derleyin")
lib = os.environ.get("ORACLE_CLIENT_LIB_DIR")
if lib:
    (ok if os.path.isdir(lib) else warn)(f"ORACLE_CLIENT_LIB_DIR={lib}" + ("" if os.path.isdir(lib) else " (dizin yok)"))
else:
    print("  [BİLGİ] ORACLE_CLIENT_LIB_DIR yok — yalnız thin mod")
if os.environ.get("AUTOMIC_FAKE", "0") not in ("", "0", "false"):
    warn("AUTOMIC_FAKE etkin — sahte veri")

print("== Modül DB şeması")
try:
    from app.services.automic import database as adb
    if not adb.automic_db_available(cache_sec=0):
        fail(f"modül DB'ye bağlanılamadı ({os.environ.get('AUTOMIC_DB_HOST')}:{os.environ.get('AUTOMIC_DB_PORT')})")
        sys.exit(1)
    adb.ensure_schema()
    db = adb._session_factory()
    ok(f"bağlı; TimescaleDB={'evet' if adb.timescale_enabled(db) else 'hayır'}; boyut={adb.database_size_bytes(db) / 1024**2:.1f} MB")
except Exception as exc:
    fail(f"modül DB: {type(exc).__name__}: {exc}")
    sys.exit(1)

print("== Sistemler")
from app.services.automic.service import list_systems, system_public, system_status
systems = list_systems(db)
if not systems:
    warn("kayıtlı sistem yok — /integrations/automic")
for s in systems:
    pub = system_public(s)
    st = system_status(db, s)
    conn = pub["connection"]
    host = conn.get("host")
    port = conn.get("port")
    print(f"  - #{s.id} {s.name} · {s.source_type} · {'etkin' if s.enabled else 'pasif'} · client={pub['clients']}")
    print(f"      bağlantı: host={host} port={port} servis={conn.get('service_name') or conn.get('dsn')} kullanıcı={conn.get('user') or conn.get('username')} şifre={'kayıtlı' if pub['has_secret'] else 'YOK'}")
    cap = pub.get("capability_summary") or {}
    if cap:
        print(f"      keşif: {cap.get('engine')} {cap.get('db_version')} · mod={cap.get('driver_mode')} · rol={cap.get('database_role')} · salt-okunur={cap.get('read_only_ok')}")
        for w in (cap.get("warnings") or [])[:5]:
            warn(f"keşif: {w}")
    else:
        warn("keşif yapılmamış")
    print(f"      collector: son başarı={st.get('last_success_at')} · watermark={st.get('watermark')} · gecikme={st.get('source_lag_sec')} sn · son satır={st.get('last_rows')}")
    if st.get("last_error"):
        warn(f"son hata: {st['last_error']}")
    if s.source_type != "fake" and host and port:
        try:
            with socket.create_connection((host, int(port)), timeout=5):
                ok(f"TCP {host}:{port} erişilebilir")
        except Exception as exc:
            fail(f"TCP {host}:{port} erişilemiyor ({exc}) — firewall/DNS kontrol edin")
db.close()
sys.exit(1 if BAD else 0)
PY
[ $? -eq 0 ] || FAILED=1

echo "== Sonuç"
if [ "$FAILED" -eq 0 ]; then echo "  Tüm kontroller tamam."; else echo "  Hata(lar) var."; exit 1; fi
