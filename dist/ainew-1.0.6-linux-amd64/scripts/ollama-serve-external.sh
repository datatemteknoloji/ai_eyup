#!/usr/bin/env bash
# Ollama'yı dışarıdan erişilebilir başlatır (0.0.0.0).
# Kullanım: ./scripts/ollama-serve-external.sh
# Veya Docker ile: docker compose --profile ollama up -d ollama

set -e
cd "$(dirname "$0")/.."

echo "Ollama dış erişim için başlatılıyor..."

if command -v docker &>/dev/null && docker compose version &>/dev/null; then
  docker compose --profile ollama up -d ollama
  echo "Ollama Docker container olarak başlatıldı. Test: curl http://$(hostname -I | awk '{print $1}'):11434/api/tags"
else
  echo "Docker yok veya compose yok; host'ta OLLAMA_HOST=0.0.0.0 ile başlatılıyor."
  echo "Arka planda çalışması için: nohup env OLLAMA_HOST=0.0.0.0 ollama serve > /var/log/ollama.log 2>&1 &"
  exec env OLLAMA_HOST=0.0.0.0 ollama serve
fi
