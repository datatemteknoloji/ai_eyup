#!/usr/bin/env bash
# dev-setup.sh — Yerel geliştirme ortamı için .env dosyasını hazırlar.
#
# install-rhel.sh production kurulumunda SECRET_KEY/POSTGRES_PASSWORD/
# ADMIN_DEFAULT_PASSWORD otomatik üretilirken, yerel geliştirme akışı
# (`cp .env.example .env`) bu adımı atlayıp geliştiriciyi elle
# `openssl rand -hex 32` çalıştırmaya bırakıyordu (devex-review bulgusu,
# 2026-08-02). Bu script aynı otomasyonu dev ortamı için sağlar.
#
# Kullanım:
#   ./scripts/dev-setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ ! -f ".env.example" ]]; then
    echo "HATA: .env.example bulunamadı." >&2
    exit 1
  fi
  cp .env.example "$ENV_FILE"
  echo "✓ .env.example -> .env kopyalandı"
else
  echo "ℹ .env zaten mevcut, sadece boş/placeholder değerler dolduruluyor"
fi

fill_env_var() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    local current
    current="$(grep "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2-)"
    if [[ -z "$current" || "$current" == CHANGE_ME* || "$current" == GENERATE_* ]]; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
      echo "✓ ${key} otomatik üretildi"
    fi
  else
    echo "${key}=${value}" >> "$ENV_FILE"
    echo "✓ ${key} eklendi"
  fi
}

fill_env_var "SECRET_KEY" "$(openssl rand -hex 32)"
fill_env_var "POSTGRES_PASSWORD" "$(openssl rand -hex 16)"

echo
echo "Tamamlandı. Sıradaki adımlar:"
echo "  1. .env içindeki OLLAMA_URL / CORS_ORIGINS değerlerini ihtiyacınıza göre düzenleyin"
echo "  2. docker compose up -d"
echo
echo "(bkz. docs/getting-started.md)"
