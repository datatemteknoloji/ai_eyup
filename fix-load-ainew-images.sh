#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Eksik ainew-backend / ainew-frontend imajlarını onarır.
#
# Tipik hata:
#   eksik imaj: ainew-backend:1.0.9.11
#   (Docker'da 1.0.9.12 yüklü veya parçalar birleşmemiş)
#
# Kullanım (kurulum dizininde, örn. /data):
#   sudo ./fix-load-ainew-images.sh
#   sudo ./fix-load-ainew-images.sh --up   # load sonrası compose up
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f "docker-compose.prod.yml" ]]; then
  COMPOSE_FILE="docker-compose.prod.yml"
else
  COMPOSE_FILE="docker-compose.yml"
fi
ENV_FILE=".env"
IMAGES_DIR="./images"
DO_UP=0
[[ "${1:-}" == "--up" ]] && DO_UP=1

c_green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red() { printf '\033[0;31m%s\033[0m\n' "$1"; }
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
  c_red "Root gerekli: sudo ./fix-load-ainew-images.sh"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  c_red "$ENV_FILE yok — önce install-rhel.sh çalıştırın."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  c_red "Docker çalışmıyor."
  exit 1
fi
DOCKER_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
[[ -n "${DOCKER_ROOT:-}" ]] && mkdir -p "${DOCKER_ROOT}/tmp"

APP_VERSION="$(tr -d '[:space:]' < VERSION 2>/dev/null || true)"
[[ -z "$APP_VERSION" ]] && APP_VERSION="latest"
BE_TARGET="ainew-backend:${APP_VERSION}"
FE_TARGET="ainew-frontend:${APP_VERSION}"
if grep -q '^BACKEND_IMAGE=' .env.example 2>/dev/null; then
  BE_TARGET="$(grep '^BACKEND_IMAGE=' .env.example | head -1 | cut -d= -f2-)"
  FE_TARGET="$(grep '^FRONTEND_IMAGE=' .env.example | head -1 | cut -d= -f2-)"
fi

set_env_var() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

step ".env imaj etiketleri → paket sürümü ($APP_VERSION)"
set_env_var "BACKEND_IMAGE" "$BE_TARGET"
set_env_var "FRONTEND_IMAGE" "$FE_TARGET"
set_env_var "APP_VERSION" "$APP_VERSION"
c_green "BACKEND_IMAGE=$BE_TARGET"
c_green "FRONTEND_IMAGE=$FE_TARGET"

step "Parça birleştirme"
if [[ -d "$IMAGES_DIR" ]] && compgen -G "${IMAGES_DIR}/*.tar.gz.part*" > /dev/null 2>&1; then
  for part1 in "${IMAGES_DIR}"/*.tar.gz.part01; do
    [[ -e "$part1" ]] || continue
    target="${part1%.part01}"
    mapfile -t sorted < <(ls -1 "${target}".part* 2>/dev/null | sort -V)
    [[ ${#sorted[@]} -eq 0 ]] && continue
    parts_size=0
    for p in "${sorted[@]}"; do
      parts_size=$((parts_size + $(stat -c%s "$p" 2>/dev/null || echo 0)))
    done
    target_size=0
    [[ -e "$target" ]] && target_size="$(stat -c%s "$target" 2>/dev/null || echo 0)"
    if [[ ! -e "$target" || "$target_size" -lt "$parts_size" ]]; then
      cat "${sorted[@]}" > "$target"
      c_green "  ✓ $(basename "$target") ($(du -h "$target" | awk '{print $1}'))"
    fi
  done
else
  c_yellow "Birleştirilecek .part* yok (veya images/ yok)."
fi

step "ainew imajlarını docker load"
for f in "$IMAGES_DIR"/ainew-backend.tar.gz "$IMAGES_DIR"/ainew-frontend.tar.gz; do
  if [[ ! -e "$f" ]]; then
    c_red "Yok: $f"
    c_yellow "images/ içeriği:"
    ls -la "$IMAGES_DIR" 2>/dev/null || true
    exit 1
  fi
  c_yellow "Yükleniyor: $(basename "$f")"
  gunzip -c "$f" | docker load
done

# Hedef etiket yoksa mevcut ainew etiketinden retag
for img in "$BE_TARGET" "$FE_TARGET"; do
  if docker image inspect "$img" >/dev/null 2>&1; then
    c_green "  ✓ $img"
    continue
  fi
  repo="${img%%:*}"
  any="$(docker images --format '{{.Repository}}:{{.Tag}}' "$repo" 2>/dev/null | grep -v '<none>' | head -1 || true)"
  if [[ -n "$any" ]]; then
    c_yellow "  retag: $any → $img"
    docker tag "$any" "$img"
    docker tag "$any" "${repo}:latest" 2>/dev/null || true
  else
    c_red "  $img yok ve retag kaynağı da yok"
    exit 1
  fi
done

c_green "İmajlar hazır."
docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}' | grep -E 'REPOSITORY|ainew-' || true

if [[ "$DO_UP" -eq 1 ]]; then
  step "Servisler başlatılıyor (--no-build)"
  set -a
  # shellcheck disable=SC1091
  source "$ENV_FILE"
  set +a
  PROFILES=()
  if [[ -f ./WITH_OLLAMA ]] || docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
    PROFILES=(--profile ollama)
  fi
  if docker compose -f "$COMPOSE_FILE" up -d --help 2>&1 | grep -q -- '--pull'; then
    docker compose "${PROFILES[@]}" -f "$COMPOSE_FILE" up -d --no-build --pull never
  else
    docker compose "${PROFILES[@]}" -f "$COMPOSE_FILE" up -d --no-build
  fi
  c_yellow "Sağlık: curl -sf http://127.0.0.1:8000/health"
fi

c_green "Tamam. Kuruluma devam: sudo ./install-rhel.sh  (veya bu betiği --up ile)"
