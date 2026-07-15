#!/bin/sh
# Backend entrypoint: bind-mount dizinlerinin sahipliğini appuser'a düzelt, sonra düşür.
set -e

APP_UID="${APP_UID:-$(id -u appuser 2>/dev/null || echo 100)}"
APP_GID="${APP_GID:-$(id -g appuser 2>/dev/null || echo 102)}"

fix_data_dir() {
  dir="$1"
  if [ ! -e "$dir" ]; then
    mkdir -p "$dir" 2>/dev/null || true
  fi
  if [ ! -d "$dir" ]; then
    return 0
  fi
  # root değilsek chown yapamayız
  if [ "$(id -u)" -ne 0 ]; then
    return 0
  fi
  # Yazılabilirlik testini appuser olarak dene; başarısızsa sahipliği düzelt
  if ! gosu appuser:appgroup sh -c "touch \"$dir/.write_probe\" 2>/dev/null && rm -f \"$dir/.write_probe\""; then
    echo "entrypoint: fixing ownership of $dir -> appuser:appgroup"
    chown -R appuser:appgroup "$dir" || true
  fi
}

fix_data_dir /var/lib/server_management/chroma
fix_data_dir /app/uploads
fix_data_dir /app/repos
fix_data_dir /app/uploads/chroma_knowledge

if [ "$(id -u)" -eq 0 ]; then
  exec gosu appuser:appgroup "$@"
fi
exec "$@"
