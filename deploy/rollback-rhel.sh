#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# RHEL 9 geri alma (rollback) betiği — Altyapı Yönetim Platformu
#
# update-rhel.sh'ın aldığı son yedeğe (veya --backup ile verilen yedeğe)
# dönerek önceki Docker imaj etiketlerini yeniden aktif eder.
#
# Kullanım (kurulum dizininden):
#   cd /data
#   sudo ./rollback-rhel.sh                  # sadece imajlar (hızlı)
#   sudo ./rollback-rhel.sh --restore-db     # imajlar + Postgres dump
#   sudo ./rollback-rhel.sh --backup /path/to/pre-update-...
#
# Notlar:
#   - Varsayılan (imaj-only) rollback: update sonrası eklenen uygulama verisi
#     (yeni sunucular vb.) KALIR; sadece uygulama kodu/imajı eski sürüme döner.
#     Şema geriye uyumlu değilse --restore-db kullanın.
#   - --restore-db: update anındaki DB snapshot'ına döner — o andan sonraki
#     TÜM DB değişiklikleri kaybolur. Onay ister.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env"

c_green()  { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red()    { printf '\033[0;31m%s\033[0m\n' "$1"; }
step()     { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

BACKUP_DIR=""
RESTORE_DB=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup) BACKUP_DIR="$2"; shift 2 ;;
    --restore-db) RESTORE_DB=1; shift ;;
    -h|--help)
      sed -n '2,22p' "$0"
      exit 0
      ;;
    *) c_red "Bilinmeyen argüman: $1"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  c_red "Bu betik root olarak çalıştırılmalı: sudo ./rollback-rhel.sh"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  c_red "$SCRIPT_DIR/$ENV_FILE bulunamadı — bu betiği kurulum dizininden çalıştırın."
  exit 1
fi

DATA_DIR="$(grep '^DATA_DIR=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
[[ -z "$DATA_DIR" ]] && DATA_DIR="$SCRIPT_DIR/data"

if [[ -z "$BACKUP_DIR" ]]; then
  if [[ -L "$DATA_DIR/backups/latest" || -d "$DATA_DIR/backups/latest" ]]; then
    BACKUP_DIR="$(readlink -f "$DATA_DIR/backups/latest")"
  else
    BACKUP_DIR="$(ls -1dt "$DATA_DIR"/backups/pre-update-* 2>/dev/null | head -1 || true)"
  fi
fi

if [[ -z "$BACKUP_DIR" || ! -d "$BACKUP_DIR" ]]; then
  c_red "Yedek bulunamadı. update-rhel.sh ile alınan bir yedek gerekli."
  c_yellow "Mevcut yedekler: ls -la $DATA_DIR/backups/"
  exit 1
fi

if [[ ! -f "$BACKUP_DIR/previous_images.txt" ]]; then
  c_red "Yedek bozuk: $BACKUP_DIR/previous_images.txt yok"
  exit 1
fi

# shellcheck disable=SC1090
source "$BACKUP_DIR/previous_images.txt"
OLD_BACKEND="${BACKEND_IMAGE:-}"
OLD_FRONTEND="${FRONTEND_IMAGE:-}"
TARGET_VERSION="${OLD_VERSION:-unknown}"

if [[ -z "$OLD_BACKEND" || -z "$OLD_FRONTEND" ]]; then
  c_red "Yedekteki imaj etiketleri boş: $BACKUP_DIR/previous_images.txt"
  exit 1
fi

CURRENT_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"

echo
c_green "════════════════════════════════════════════════════════════════"
c_green " Geri alma (rollback)"
c_green "════════════════════════════════════════════════════════════════"
echo " Kurulum       : $SCRIPT_DIR"
echo " Yedek         : $BACKUP_DIR"
echo " Şu an         : $CURRENT_VERSION"
echo " Hedef         : $TARGET_VERSION"
echo " İmajlar       : $OLD_BACKEND / $OLD_FRONTEND"
echo " DB geri al    : $([[ "$RESTORE_DB" == "1" ]] && echo EVET || echo hayır)"
echo

# İmajların Docker'da hâlâ durduğunu doğrula
if ! docker image inspect "$OLD_BACKEND" >/dev/null 2>&1; then
  c_red "Docker'da eski backend imajı yok: $OLD_BACKEND"
  c_yellow "Eski sürüm paketinin images/ dizininden yükleyin:"
  c_yellow "  gunzip -c /path/to/ainew-${TARGET_VERSION}-*/images/ainew-backend.tar.gz | docker load"
  exit 1
fi
if ! docker image inspect "$OLD_FRONTEND" >/dev/null 2>&1; then
  c_red "Docker'da eski frontend imajı yok: $OLD_FRONTEND"
  exit 1
fi

if [[ "$RESTORE_DB" == "1" ]]; then
  if [[ ! -f "$BACKUP_DIR/db.sql" ]]; then
    c_red "Bu yedekte db.sql yok — imaj-only rollback yapabilirsiniz ( --restore-db olmadan )."
    exit 1
  fi
  echo
  c_yellow "⚠ --restore-db: Postgres, güncelleme anındaki haline dönecek."
  c_yellow "  O andan sonraki TÜM veritabanı değişiklikleri silinir."
  if [[ -t 0 ]]; then
    read -rp "Devam etmek için 'EVET' yazın: " CONFIRM
    [[ "$CONFIRM" == "EVET" ]] || { c_red "İptal."; exit 1; }
  fi
fi

# ── 1. İmaj etiketlerini geri al ────────────────────────────────────────────
step ".env imaj etiketleri eski sürüme çekiliyor"
set_env() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}
set_env "BACKEND_IMAGE"  "$OLD_BACKEND"
set_env "FRONTEND_IMAGE" "$OLD_FRONTEND"
[[ -f "$BACKUP_DIR/VERSION" ]] && cp -a "$BACKUP_DIR/VERSION" VERSION
c_green "BACKEND_IMAGE=$OLD_BACKEND"
c_green "FRONTEND_IMAGE=$OLD_FRONTEND"

# ── 2. DB geri yükleme (opsiyonel) ──────────────────────────────────────────
set -a; # shellcheck disable=SC1091
source "$ENV_FILE"
set +a

if [[ "$RESTORE_DB" == "1" ]]; then
  step "Postgres yedeği geri yükleniyor"
  # Backend'i durdur ki bağlantı tutmasın; db ayakta kalsın
  docker compose -f "$COMPOSE_FILE" stop backend frontend 2>/dev/null || true
  docker compose -f "$COMPOSE_FILE" up -d db
  sleep 5
  docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='server_management' AND pid <> pg_backend_pid();" \
    >/dev/null 2>&1 || true
  docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U postgres -c "DROP DATABASE IF EXISTS server_management;"
  docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U postgres -c "CREATE DATABASE server_management;"
  docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U postgres -d server_management < "$BACKUP_DIR/db.sql"
  c_green "DB geri yüklendi."
fi

# ── 3. Servisleri eski imajlarla başlat ─────────────────────────────────────
step "Servisler eski imajlarla başlatılıyor"
docker compose -f "$COMPOSE_FILE" up -d

step "Sağlık kontrolü"
READY=0
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 3
done

echo
if [[ "$READY" -eq 1 ]]; then
  c_green "✔ Rollback tamamlandı → sürüm $TARGET_VERSION"
else
  c_red "⚠ Backend yanıt vermiyor. Log:"
  c_yellow "  docker compose -f $COMPOSE_FILE logs --tail=50 backend"
fi
echo
