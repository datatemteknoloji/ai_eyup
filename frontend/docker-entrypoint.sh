#!/bin/sh
# Frontend nginx entrypoint — eksik TLS sertifikasını self-signed üretir.
# Mount: ${DATA_DIR}/certs → /etc/nginx/certs (yazılabilir olmalı; :ro olmamalı).
set -eu

CERT_DIR="${CERT_DIR:-/etc/nginx/certs}"
CERT="${CERT_DIR}/server.crt"
KEY="${CERT_DIR}/server.key"

mkdir -p "$CERT_DIR"

if [ ! -f "$CERT" ] || [ ! -f "$KEY" ]; then
  echo "ainew-frontend: TLS sertifikası yok — self-signed üretiliyor (${CERT_DIR})"
  CN="${TLS_CN:-localhost}"
  # subjectAltName: isteğe bağlı IP + localhost
  if [ -n "${TLS_IP:-}" ]; then
    SAN="IP:${TLS_IP},DNS:localhost,DNS:${CN}"
  else
    SAN="DNS:localhost,DNS:${CN},IP:127.0.0.1"
  fi
  if ! command -v openssl >/dev/null 2>&1; then
    echo "ainew-frontend: HATA — openssl yok; sertifika üretilemedi." >&2
    echo "  Host'ta: install-rhel.sh veya openssl ile ${CERT_DIR}/server.crt + server.key oluşturun." >&2
    exit 1
  fi
  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$KEY" -out "$CERT" \
    -subj "/C=TR/O=ainew/CN=${CN}" \
    -addext "subjectAltName=${SAN}"
  chmod 644 "$CERT" 2>/dev/null || true
  chmod 600 "$KEY" 2>/dev/null || true
  echo "ainew-frontend: self-signed sertifika hazır (CN=${CN})."
else
  echo "ainew-frontend: mevcut TLS sertifikası kullanılıyor."
fi

exec nginx -g "daemon off;"
