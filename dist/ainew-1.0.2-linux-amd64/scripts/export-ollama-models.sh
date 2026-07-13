#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Ollama modellerini air-gapped (internet erişimi olmayan) müşteri kurulumlarına
# taşımak için dışa aktarır. Modelleri imaja gömmek yerine (multi-GB, imaj
# şişirir) bu betikle önceden indirilmiş modelleri ayrı bir tarball olarak
# paketleyip hedef sunucuya taşıyın; import-ollama-models.sh ile geri yükleyin.
#
# Kullanım (modellerin zaten `ollama pull` ile indirildiği kaynak makinede):
#   ./scripts/export-ollama-models.sh [çıktı-dosyası] [ollama-veri-dizini]
#
# Varsayılanlar:
#   çıktı-dosyası      : ollama-models.tar.gz
#   ollama-veri-dizini : /var/lib/server_management/ollama
#                        (docker-compose.prod.yml'deki ollama servisinin volume'ü)
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

OUT_FILE="${1:-ollama-models.tar.gz}"
OLLAMA_DIR="${2:-/var/lib/server_management/ollama}"

if [[ ! -d "$OLLAMA_DIR" ]]; then
  echo "✗ Ollama veri dizini bulunamadı: $OLLAMA_DIR" >&2
  echo "  Farklı bir yol kullanıyorsanız: $0 <çıktı-dosyası> <ollama-veri-dizini>" >&2
  exit 1
fi

if [[ -z "$(ls -A "$OLLAMA_DIR" 2>/dev/null)" ]]; then
  echo "✗ $OLLAMA_DIR boş görünüyor — önce 'ollama pull <model>' ile en az bir model indirin." >&2
  exit 1
fi

echo "▶ Kaynak     : $OLLAMA_DIR"
echo "▶ Çıktı      : $OUT_FILE"
echo "▶ Modeller dışa aktarılıyor (bu birkaç dakika ve birkaç GB sürebilir)..."

tar czf "$OUT_FILE" -C "$OLLAMA_DIR" .
sha256sum "$OUT_FILE" > "${OUT_FILE}.sha256"

du -sh "$OUT_FILE"
echo
echo "✔ Hazır: $OUT_FILE"
echo "  Hedef sunucuya taşıyın (scp/USB), sonra orada çalıştırın:"
echo "    ./scripts/import-ollama-models.sh $(basename "$OUT_FILE")"
