#!/usr/bin/env bash
# Tüm servisleri build edip başlat.
# Kullanım: ./run.sh       → arka planda
#          ./run.sh -f     → ön planda (loglar terminalde)

set -e
cd "$(dirname "$0")"

# Veri dizinleri (opsiyonel; Docker volume mount ile de oluşabilir)
mkdir -p /var/lib/server_management/chroma /var/lib/server_management/redis /var/lib/server_management/prometheus 2>/dev/null || true

COMPOSE="docker-compose"
command -v docker-compose >/dev/null 2>&1 || COMPOSE="docker compose"

if [ "$1" = "-f" ] || [ "$1" = "--foreground" ]; then
  $COMPOSE up --build
else
  $COMPOSE up --build -d
  echo ""
  echo "Servisler arka planda başlatıldı."
  echo "  Frontend:  http://localhost:3000"
  echo "  Backend:   http://localhost:8000"
  echo "  Prometheus: http://localhost:9090"
  echo ""
  echo "Loglar: $COMPOSE logs -f"
  echo "Durdur: $COMPOSE down"
fi
