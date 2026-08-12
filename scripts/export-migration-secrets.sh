#!/usr/bin/env bash
# Taşıma secret dosyası — host .env'den (UI alternatifi).
# Kullanım:
#   ./scripts/export-migration-secrets.sh
#   ./scripts/export-migration-secrets.sh /dttadvance/app /tmp/ainew-migrate-secrets.env
#   ./scripts/export-migration-secrets.sh /data/app
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${1:-$ROOT_DIR}"
OUT="${2:-./ainew-migrate-secrets.env}"

ENV_FILE="$INSTALL_DIR/.env"
DROPT_ENV="$INSTALL_DIR/dropt/.env"

[[ -f "$ENV_FILE" ]] || { echo "HATA: $ENV_FILE yok" >&2; exit 1; }

get() {
  local f="$1" k="$2"
  [[ -f "$f" ]] || { echo ""; return; }
  grep -E "^${k}=" "$f" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true
}

fp16() {
  local v="$1"
  [[ -z "$v" ]] && { echo "none"; return; }
  printf '%s' "$v" | sha256sum | awk '{print "sha256:" substr($1,1,16)}'
}

SK="$(get "$ENV_FILE" SECRET_KEY)"
BRIDGE="$(get "$ENV_FILE" AINEW_BRIDGE_SECRET)"
PG="$(get "$ENV_FILE" POSTGRES_PASSWORD)"
DPG="$(get "$ENV_FILE" DROPT_POSTGRES_PASSWORD)"
FERNET="$(get "$DROPT_ENV" FERNET_KEY)"
JWT="$(get "$DROPT_ENV" JWT_SECRET)"
[[ -z "$(get "$DROPT_ENV" AINEW_BRIDGE_SECRET)" ]] || BRIDGE_D="$(get "$DROPT_ENV" AINEW_BRIDGE_SECRET)"
BRIDGE_D="${BRIDGE_D:-$BRIDGE}"

umask 077
{
  echo "# ainew migration secrets — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# Kaynak: $INSTALL_DIR"
  echo "# Fingerprint SECRET_KEY: $(fp16 "$SK")"
  echo "# Fingerprint AINEW_BRIDGE_SECRET: $(fp16 "$BRIDGE")"
  echo "# Fingerprint FERNET_KEY: $(fp16 "$FERNET")"
  echo "#"
  echo "# Hedefte BLOK A → <INSTALL>/.env  |  BLOK B → <INSTALL>/dropt/.env"
  echo "# Sonra: docker compose up -d --force-recreate backend worker"
  echo "# AINEW_INSTALL_DIR / DATA_DIR / CORS kopyalamayın."
  echo "#"
  echo "# === BLOK A: ana .env ==="
  echo "SECRET_KEY=${SK}"
  echo "AINEW_BRIDGE_SECRET=${BRIDGE}"
  echo "POSTGRES_PASSWORD=${PG}"
  echo "DROPT_POSTGRES_PASSWORD=${DPG}"
  echo "#"
  echo "# === BLOK B: dropt/.env ==="
  echo "FERNET_KEY=${FERNET}"
  echo "AINEW_BRIDGE_SECRET=${BRIDGE_D}"
  echo "JWT_SECRET=${JWT}"
  echo "POSTGRES_PASSWORD=${DPG}"
  echo
} > "$OUT"
chmod 600 "$OUT"
echo "Yazıldı: $OUT"
echo "SECRET_KEY fingerprint: $(fp16 "$SK")"
