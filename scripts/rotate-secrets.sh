#!/usr/bin/env bash
# rotate-secrets.sh — Canlı ortamda SECRET_KEY (ve isteğe bağlı POSTGRES_PASSWORD) güçlendir.
#
# 1) Fernet alanlarını old→new re-encrypt eder
# 2) .env SECRET_KEY günceller
# 3) Backend (+ worker) recreate
# 4) --postgres: Postgres rol parolasını ALTER + .env güncelle
#
# Kullanım:
#   ./scripts/rotate-secrets.sh
#   ./scripts/rotate-secrets.sh --postgres
#   ./scripts/rotate-secrets.sh --dry-run
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
BACKEND_CTR="${BACKEND_CONTAINER:-server_management_backend}"
DB_CTR="${DB_CONTAINER:-server_management_db}"
DO_POSTGRES=0
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --postgres) DO_POSTGRES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "HATA: $ENV_FILE yok" >&2
  exit 1
fi

is_placeholder() {
  local v="${1:-}"
  [[ -z "$v" ]] && return 0
  local u
  u="$(printf '%s' "$v" | tr '[:lower:]' '[:upper:]')"
  [[ "$u" == CHANGE_ME* || "$u" == GENERATE_* || "$u" == REPLACE-* || "$u" == TODO* || "$u" == YOUR_* ]] && return 0
  [[ "${#v}" -lt 16 ]] && return 0
  return 1
}

get_env() {
  grep -E "^${1}=" "$ENV_FILE" | head -1 | cut -d= -f2- || true
}

set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

OLD_KEY="$(get_env SECRET_KEY)"
if [[ -z "$OLD_KEY" ]]; then
  echo "HATA: SECRET_KEY .env'de yok" >&2
  exit 1
fi

NEW_KEY="$(openssl rand -hex 32)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${ENV_FILE}.bak-rotate-${TS}"

echo "==> .env yedeği: $BACKUP"
cp -a "$ENV_FILE" "$BACKUP"
chmod 600 "$BACKUP" "$ENV_FILE" 2>/dev/null || true

echo "==> Eski SECRET_KEY sha256[0:16]: $(printf '%s' "$OLD_KEY" | sha256sum | awk '{print substr($1,1,16)}')"
echo "==> Yeni SECRET_KEY üretildi (değer yazdırılmaz)"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] DB re-encrypt + .env güncellemesi atlandı"
  exit 0
fi

if ! docker inspect "$BACKEND_CTR" >/dev/null 2>&1; then
  echo "HATA: container yok: $BACKEND_CTR" >&2
  exit 1
fi

echo "==> Fernet alanları yeniden şifreleniyor ($BACKEND_CTR)…"
OUT="$(
  docker exec -e "OLD_SECRET_KEY=${OLD_KEY}" -e "NEW_SECRET_KEY=${NEW_KEY}" \
    "$BACKEND_CTR" python -m app.scripts.rotate_secret_key
)" || {
  echo "HATA: rotate başarısız — .env değiştirilmedi. Yedek: $BACKUP" >&2
  echo "$OUT" >&2
  exit 1
}
echo "$OUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("   ok fields=",d.get("fields"),"rows~=",d.get("rows"),"details=",d.get("details"))' 2>/dev/null \
  || echo "   $OUT"

echo "==> .env SECRET_KEY güncelleniyor"
set_env "SECRET_KEY" "$NEW_KEY"

if [[ "$DO_POSTGRES" -eq 1 ]]; then
  OLD_PG="$(get_env POSTGRES_PASSWORD)"
  NEW_PG="$(openssl rand -hex 16)"
  echo "==> Postgres parolası döndürülüyor…"
  if ! docker exec -e PGPASSWORD="${OLD_PG}" -e NEW_PG="${NEW_PG}" "$DB_CTR" \
      bash -lc 'psql -U postgres -v ON_ERROR_STOP=1 -c "ALTER USER postgres PASSWORD '\''${NEW_PG}'\'';"'; then
    echo "HATA: ALTER USER başarısız — SECRET_KEY güncellendi, Postgres eski kaldı" >&2
    echo "      Yedek: $BACKUP" >&2
    exit 1
  fi
  set_env "POSTGRES_PASSWORD" "$NEW_PG"
  python3 - <<PY
from pathlib import Path
import re
p = Path("$ENV_FILE")
text = p.read_text()
new_pg = """$NEW_PG"""
text2, n = re.subn(
    r"(DATABASE_URL=postgresql://[^:]+:)([^@]+)(@)",
    lambda m: m.group(1) + new_pg + m.group(3),
    text,
    count=1,
)
if n:
    p.write_text(text2)
    print("   DATABASE_URL parola güncellendi")
PY
  echo "   POSTGRES_PASSWORD güncellendi"
fi

echo "==> Backend / worker yeniden oluşturuluyor…"
if [[ -f docker-compose.yml ]]; then
  docker compose up -d --force-recreate backend worker 2>/dev/null \
    || docker compose up -d --force-recreate backend
else
  docker restart "$BACKEND_CTR"
fi

echo "==> Sağlık kontrolü…"
ok=0
for _ in $(seq 1 15); do
  if curl -sf http://127.0.0.1:8000/api/v1/public/version >/dev/null 2>&1; then
    echo "   API ayakta"
    ok=1
    break
  fi
  sleep 2
done
[[ "$ok" -eq 1 ]] || echo "   UYARI: API henüz yanıt vermiyor — logları kontrol edin"

NEW_CHECK="$(get_env SECRET_KEY)"
if is_placeholder "$NEW_CHECK"; then
  echo "HATA: SECRET_KEY hâlâ zayıf görünüyor" >&2
  exit 1
fi

# Kısa doğrulama (yeni container env)
sleep 2
docker exec "$BACKEND_CTR" python -u - <<'PY'
from app.services.secret_policy import validate_runtime_secrets, secret_key_fingerprint
import os
ok, msgs = validate_runtime_secrets()
print("fingerprint", secret_key_fingerprint(os.environ.get("SECRET_KEY","")))
print("validate_ok", ok)
for m in msgs:
    print("msg:", m)
raise SystemExit(0 if ok else 1)
PY

echo
echo "Tamam. Oturumlar düşmüş olabilir — yeniden giriş yapın."
echo "Taşıma: bu .env SECRET_KEY ile birlikte DB yedeğini hedefe götürün."
echo "Doküman: docs/migration-and-secrets.md"
echo "Yedek .env: $BACKUP"
