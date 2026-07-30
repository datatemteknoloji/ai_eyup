#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# RAG embedding için Ollama + nomic-embed-text hazırla.
#
# Müşteri / prod sunucusunda (örn. 10.51.13.54) Ayarlar → RAG ekranında
# "http://127.0.0.1:11434 erişilemedi" görürseniz bu betiği kurulum
# dizininde çalıştırın.
#
# Kullanım:
#   sudo ./scripts/ensure-rag-ollama.sh
#   sudo ./scripts/ensure-rag-ollama.sh --install-dir /data
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/data"
COMPOSE_FILE="docker-compose.prod.yml"
EMBED_MODEL="${OLLAMA_EMBED_MODEL:-nomic-embed-text}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --compose) COMPOSE_FILE="$2"; shift 2 ;;
    --model) EMBED_MODEL="$2"; shift 2 ;;
    *) echo "Bilinmeyen argüman: $1"; exit 1 ;;
  esac
done

cd "$INSTALL_DIR"

echo "▶ Kurulum dizini: $INSTALL_DIR"
echo "▶ Embed model   : $EMBED_MODEL"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
echo "▶ OLLAMA_URL    : $OLLAMA_URL"

probe() {
  curl -sf --max-time 5 "${OLLAMA_URL%/}/api/tags" >/dev/null 2>&1
}

if ! probe; then
  echo "▶ Ollama yanıt vermiyor — compose profile 'ollama' ile başlatılıyor..."
  if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "ERROR: $INSTALL_DIR/$COMPOSE_FILE yok. Kurulum dizinini kontrol edin."
    exit 1
  fi
  docker compose --profile ollama -f "$COMPOSE_FILE" up -d ollama
  echo "▶ Ollama ayağa kalkması bekleniyor..."
  for i in $(seq 1 60); do
    if probe; then
      echo "✔ Ollama hazır ($i sn)"
      break
    fi
    sleep 2
    if [[ "$i" -eq 60 ]]; then
      echo "ERROR: Ollama 120 sn içinde ${OLLAMA_URL} üzerinde yanıt vermedi."
      echo "  - systemctl / docker logs server_management_ollama"
      echo "  - .env içinde OLLAMA_URL doğru mu?"
      exit 1
    fi
  done
else
  echo "✔ Ollama erişilebilir: $OLLAMA_URL"
fi

echo "▶ Model çekiliyor: $EMBED_MODEL"
if docker ps --format '{{.Names}}' | grep -qx 'server_management_ollama'; then
  docker exec server_management_ollama ollama pull "$EMBED_MODEL"
elif command -v ollama >/dev/null 2>&1; then
  ollama pull "$EMBED_MODEL"
else
  echo "WARN: ollama CLI / container bulunamadı — modeli elle pull edin."
fi

echo "▶ Embedding smoke test..."
curl -sf --max-time 60 "${OLLAMA_URL%/}/api/embeddings" \
  -d "{\"model\":\"${EMBED_MODEL}\",\"prompt\":\"rag smoke\"}" \
  | grep -q embedding && echo "✔ Embedding OK" || {
    echo "ERROR: embedding isteği başarısız. Model adı ve Ollama loglarını kontrol edin."
    exit 1
  }

echo
echo "✔ RAG embedding hazır. Ayarlar → RAG → 'Şimdi tümünü yenile' çalıştırın."
echo "  Backend OLLAMA_URL görmüyorsa: docker compose -f $COMPOSE_FILE up -d --force-recreate backend"
