#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# export-ollama-models.sh ile üretilmiş model tarball'ını air-gapped hedef
# sunucuda geri yükler. `ollama` servisi başlamadan (veya durdurulduktan
# sonra) çalıştırılmalıdır — çalışırken üzerine yazmak dosya bozulmasına
# yol açabilir.
#
# Kullanım:
#   ./scripts/import-ollama-models.sh <tarball> [ollama-veri-dizini]
#
# Varsayılan ollama-veri-dizini: /data/data/ollama
#   (docker-compose.prod.yml'deki ollama servisinin volume'ü)
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

TARBALL="${1:-}"
OLLAMA_DIR="${2:-/data/data/ollama}"

if [[ -z "$TARBALL" || ! -f "$TARBALL" ]]; then
  echo "Kullanım: $0 <tarball> [ollama-veri-dizini]" >&2
  echo "✗ Tarball bulunamadı: ${TARBALL:-<belirtilmedi>}" >&2
  exit 1
fi

if [[ -f "${TARBALL}.sha256" ]]; then
  echo "▶ Bütünlük kontrol ediliyor (sha256)..."
  ( cd "$(dirname "$TARBALL")" && sha256sum -c "$(basename "${TARBALL}.sha256")" )
fi

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^server_management_ollama$'; then
  echo "⚠ 'server_management_ollama' konteyneri çalışıyor görünüyor."
  echo "  Önce durdurun: docker compose -f docker-compose.prod.yml stop ollama"
  read -r -p "  Yine de devam edilsin mi? (evet/hayır): " CONFIRM
  [[ "$CONFIRM" == "evet" ]] || { echo "İptal edildi."; exit 1; }
fi

mkdir -p "$OLLAMA_DIR"

echo "▶ Kaynak     : $TARBALL"
echo "▶ Hedef      : $OLLAMA_DIR"
echo "▶ Modeller geri yükleniyor..."

tar xzf "$TARBALL" -C "$OLLAMA_DIR"

echo
echo "✔ Tamamlandı. Modeller doğrulanıyor..."
if command -v docker >/dev/null 2>&1 && docker compose -f docker-compose.prod.yml ps ollama >/dev/null 2>&1; then
  docker compose -f docker-compose.prod.yml up -d ollama
  sleep 2
  docker compose -f docker-compose.prod.yml exec -T ollama ollama list || true
else
  echo "  (ollama servisini başlatıp 'ollama list' ile modelleri doğrulayabilirsiniz)"
fi
