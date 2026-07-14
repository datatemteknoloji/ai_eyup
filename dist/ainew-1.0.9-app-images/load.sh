#!/usr/bin/env bash
# ainew 1.0.9 — sadece uygulama imajlarını yükler (DB/Redis ayrı kalır)
set -euo pipefail
cd "$(dirname "$0")"

join_parts() {
  local base="$1"
  if [[ -f "${base}" ]]; then
    echo "${base}"
    return
  fi
  if compgen -G "${base}.part*" > /dev/null; then
    cat ${base}.part* > "${base}"
    echo "${base}"
    return
  fi
  echo "Bulunamadı: ${base}" >&2
  exit 1
}

echo "▶ ainew-backend:1.0.9 yükleniyor..."
BE=$(join_parts ainew-backend.tar.gz)
gunzip -c "$BE" | docker load
echo "▶ ainew-frontend:1.0.9 yükleniyor..."
FE=$(join_parts ainew-frontend.tar.gz)
gunzip -c "$FE" | docker load

docker tag "ainew-backend:1.0.9" ainew-backend:latest
docker tag "ainew-frontend:1.0.9" ainew-frontend:latest

echo
echo "✔ Yüklendi:"
docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -E 'ainew-(backend|frontend):(latest|1.0.9)' || true
echo
echo "Mevcut kurulumda .env:"
echo "  APP_VERSION=1.0.9"
echo "  BACKEND_IMAGE=ainew-backend:1.0.9"
echo "  FRONTEND_IMAGE=ainew-frontend:1.0.9"
echo "Ardından: docker compose -f docker-compose.prod.yml up -d backend frontend"
