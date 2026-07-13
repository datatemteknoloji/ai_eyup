#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# RHEL 9 güncelleme betiği — Altyapı Yönetim Platformu
#
# Yeni sürüm paketini mevcut kuruluma uygular. Kalıcı veri (DATA_DIR) dokunulmaz.
# Güncellemeden ÖNCE otomatik yedek alınır; sorun olursa rollback-rhel.sh ile
# önceki sürüme dönülebilir.
#
# Kullanım (yeni paket dizininden):
#   tar xzf ainew-1.0.1-linux-amd64.tar.gz
#   cd ainew-1.0.1-linux-amd64
#   sudo ./update-rhel.sh --install-dir /opt/ainew
#
# Ortam değişkenleri:
#   INSTALL_DIR   Hedef kurulum (varsayılan: --install-dir veya /opt/ainew)
#   SKIP_DB_BACKUP=1  Postgres dump atlanır (hızlı ama rollback'te DB geri alınamaz)
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

NEW_PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env"
DEFAULT_INSTALL_DIR="/opt/ainew"

c_green()  { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red()    { printf '\033[0;31m%s\033[0m\n' "$1"; }
step()     { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

INSTALL_DIR="${INSTALL_DIR:-}"
SKIP_DB_BACKUP="${SKIP_DB_BACKUP:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --skip-db-backup) SKIP_DB_BACKUP=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) c_red "Bilinmeyen argüman: $1"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  c_red "Bu betik root olarak çalıştırılmalı: sudo ./update-rhel.sh"
  exit 1
fi

if [[ -z "$INSTALL_DIR" ]]; then
  if [[ -t 0 ]]; then
    read -rp "Mevcut kurulum dizini [${DEFAULT_INSTALL_DIR}]: " INSTALL_DIR
    INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
  else
    INSTALL_DIR="$DEFAULT_INSTALL_DIR"
  fi
fi
INSTALL_DIR="$(realpath -m "$INSTALL_DIR")"

if [[ ! -f "$INSTALL_DIR/$ENV_FILE" ]]; then
  c_red "Kurulum bulunamadı: $INSTALL_DIR/$ENV_FILE"
  c_yellow "İlk kurulum için: sudo ./install-rhel.sh"
  exit 1
fi

if [[ "$NEW_PKG_DIR" == "$INSTALL_DIR" ]]; then
  c_red "update-rhel.sh yeni paket dizininden çalıştırılmalı, kurulum dizininin içinden değil."
  c_yellow "Örnek: cd /root/ainew-1.0.1-linux-amd64 && sudo ./update-rhel.sh --install-dir $INSTALL_DIR"
  exit 1
fi

DATA_DIR="$(grep '^DATA_DIR=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2-)"
[[ -z "$DATA_DIR" ]] && DATA_DIR="$INSTALL_DIR/data"

OLD_VERSION="$(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo "unknown")"
NEW_VERSION="$(cat "$NEW_PKG_DIR/VERSION" 2>/dev/null || echo "unknown")"
OLD_BACKEND="$(grep '^BACKEND_IMAGE=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2- || true)"
OLD_FRONTEND="$(grep '^FRONTEND_IMAGE=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2- || true)"
NEW_BACKEND="$(grep '^BACKEND_IMAGE=' "$NEW_PKG_DIR/.env.example" 2>/dev/null | head -1 | cut -d= -f2- || true)"
NEW_FRONTEND="$(grep '^FRONTEND_IMAGE=' "$NEW_PKG_DIR/.env.example" 2>/dev/null | head -1 | cut -d= -f2- || true)"
[[ -z "$NEW_BACKEND" ]]  && NEW_BACKEND="ainew-backend:${NEW_VERSION}"
[[ -z "$NEW_FRONTEND" ]] && NEW_FRONTEND="ainew-frontend:${NEW_VERSION}"

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$DATA_DIR/backups/pre-update-${OLD_VERSION}-to-${NEW_VERSION}-${TS}"

echo
c_green "════════════════════════════════════════════════════════════════"
c_green " Güncelleme: ${OLD_VERSION} → ${NEW_VERSION}"
c_green "════════════════════════════════════════════════════════════════"
echo " Kurulum      : $INSTALL_DIR"
echo " Veri         : $DATA_DIR"
echo " Eski imajlar : ${OLD_BACKEND:-?} / ${OLD_FRONTEND:-?}"
echo " Yeni imajlar : $NEW_BACKEND / $NEW_FRONTEND"
echo " Yedek        : $BACKUP_DIR"
echo

# ── 1. Yedek ────────────────────────────────────────────────────────────────
step "Güncelleme öncesi yedek alınıyor"
mkdir -p "$BACKUP_DIR"
cp -a "$INSTALL_DIR/$ENV_FILE" "$BACKUP_DIR/env"
[[ -f "$INSTALL_DIR/VERSION" ]] && cp -a "$INSTALL_DIR/VERSION" "$BACKUP_DIR/VERSION" || true
cat > "$BACKUP_DIR/previous_images.txt" <<EOF
BACKEND_IMAGE=${OLD_BACKEND}
FRONTEND_IMAGE=${OLD_FRONTEND}
OLD_VERSION=${OLD_VERSION}
NEW_VERSION=${NEW_VERSION}
INSTALL_DIR=${INSTALL_DIR}
DATA_DIR=${DATA_DIR}
EOF

if [[ "$SKIP_DB_BACKUP" != "1" ]]; then
  c_yellow "Postgres dump alınıyor (birkaç dakika sürebilir)..."
  set -a; # shellcheck disable=SC1091
  source "$INSTALL_DIR/$ENV_FILE"
  set +a
  if docker compose -f "$INSTALL_DIR/$COMPOSE_FILE" --project-directory "$INSTALL_DIR" \
      exec -T db pg_dump -U postgres server_management > "$BACKUP_DIR/db.sql" 2>/dev/null; then
    c_green "DB yedeği: $BACKUP_DIR/db.sql ($(du -h "$BACKUP_DIR/db.sql" | awk '{print $1}'))"
  else
    c_yellow "DB dump alınamadı (db ayakta değil olabilir) — sadece imaj rollback mümkün olacak."
    rm -f "$BACKUP_DIR/db.sql"
  fi
else
  c_yellow "SKIP_DB_BACKUP=1 — Postgres dump atlandı."
fi
ln -sfn "$BACKUP_DIR" "$DATA_DIR/backups/latest"
c_green "Yedek tamam: $BACKUP_DIR"

# ── 2. Paket dosyalarını kurulum dizinine kopyala (veri/.env hariç) ─────────
step "Yeni paket dosyaları kuruluma kopyalanıyor"
# data/ ve .env asla üzerine yazılmaz — kalıcı yapılandırma ve DB korunur.
if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude '.env' \
    --exclude 'data/' \
    --exclude '.git/' \
    --exclude 'backups/' \
    "$NEW_PKG_DIR"/ "$INSTALL_DIR"/
else
  # rsync yoksa: .env'i geçici sakla, kopyala, geri koy
  cp -a "$INSTALL_DIR/$ENV_FILE" "/tmp/ainew-env-preserve-$$"
  cp -a "$NEW_PKG_DIR"/. "$INSTALL_DIR"/
  mv "/tmp/ainew-env-preserve-$$" "$INSTALL_DIR/$ENV_FILE"
fi
chmod +x "$INSTALL_DIR"/install-rhel.sh "$INSTALL_DIR"/update-rhel.sh "$INSTALL_DIR"/rollback-rhel.sh 2>/dev/null || true
c_green "Paket dosyaları güncellendi ( .env ve data/ korundu )."

# ── 3. İmaj etiketlerini .env'de güncelle ───────────────────────────────────
step ".env imaj etiketleri güncelleniyor"
set_env() {
  local key="$1" value="$2" file="$3"
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}
set_env "BACKEND_IMAGE"  "$NEW_BACKEND"  "$INSTALL_DIR/$ENV_FILE"
set_env "FRONTEND_IMAGE" "$NEW_FRONTEND" "$INSTALL_DIR/$ENV_FILE"
c_green "BACKEND_IMAGE=$NEW_BACKEND"
c_green "FRONTEND_IMAGE=$NEW_FRONTEND"

# ── 4. Yeni imajları yükle ──────────────────────────────────────────────────
step "Yeni Docker imajları yükleniyor"
IMAGES_DIR="$INSTALL_DIR/images"
if compgen -G "${IMAGES_DIR}/*.tar.gz.part*" > /dev/null 2>&1; then
  c_yellow "Parçalanmış imaj arşivleri birleştiriliyor..."
  for part1 in "${IMAGES_DIR}"/*.tar.gz.part01; do
    [[ -e "$part1" ]] || continue
    target="${part1%.part01}"
    if [[ ! -e "$target" ]]; then
      cat "${target}".part* > "$target"
      c_green "  ✓ $(basename "$target")"
    fi
  done
fi

if [[ -d "$IMAGES_DIR" ]] && compgen -G "${IMAGES_DIR}/*.tar*" > /dev/null; then
  for f in "$IMAGES_DIR"/ainew-backend.tar.gz "$IMAGES_DIR"/ainew-frontend.tar.gz; do
    [[ -e "$f" ]] || continue
    c_yellow "Yükleniyor: $(basename "$f")"
    gunzip -c "$f" | docker load
  done
  # Eski üçüncü parti imajlar genelde aynı kalır; varsa yükle (zararsız)
  for f in "$IMAGES_DIR"/timescaledb.tar.gz "$IMAGES_DIR"/redis.tar.gz \
           "$IMAGES_DIR"/prometheus.tar.gz "$IMAGES_DIR"/pushgateway.tar.gz; do
    [[ -e "$f" ]] || continue
    gunzip -c "$f" | docker load >/dev/null || true
  done
  c_green "İmajlar yüklendi."
else
  c_yellow "images/ yok — kaynak koddan derleniyor..."
  ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" build backend frontend )
fi

# Eski imajları SİLME — rollback için docker'da kalsınlar.
c_yellow "Not: Eski imajlar (${OLD_BACKEND:-eski} / ${OLD_FRONTEND:-eski}) rollback için Docker'da bırakıldı."

# ── 5. Servisleri yeni imajlarla ayağa kaldır ───────────────────────────────
step "Servisler yeniden başlatılıyor"
cd "$INSTALL_DIR"
set -a; # shellcheck disable=SC1091
source "$ENV_FILE"
set +a
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
  c_green "✔ Güncelleme tamamlandı: ${OLD_VERSION} → ${NEW_VERSION}"
else
  c_red "⚠ Backend henüz yanıt vermiyor."
  c_yellow "  Log: cd $INSTALL_DIR && docker compose -f $COMPOSE_FILE logs --tail=50 backend"
  c_yellow "  Geri dön: cd $INSTALL_DIR && sudo ./rollback-rhel.sh"
fi

echo
c_green "════════════════════════════════════════════════════════════════"
echo " Aktif sürüm  : $NEW_VERSION"
echo " Yedek        : $BACKUP_DIR"
echo " Geri dönüş   : cd $INSTALL_DIR && sudo ./rollback-rhel.sh"
echo "               (DB de geri alınacaksa: sudo ./rollback-rhel.sh --restore-db)"
c_green "════════════════════════════════════════════════════════════════"
echo
