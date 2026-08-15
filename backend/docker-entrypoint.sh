#!/bin/sh
# Backend entrypoint: bind-mount dizinlerinin sahipliğini appuser'a düzelt, sonra düşür.
# Process worker dosyasından UVICORN_WORKERS / CELERY_CONCURRENCY uygular.
set -e

fix_data_dir() {
  dir="$1"
  if [ ! -e "$dir" ]; then
    mkdir -p "$dir" 2>/dev/null || true
  fi
  if [ ! -d "$dir" ]; then
    return 0
  fi
  if [ "$(id -u)" -ne 0 ]; then
    return 0
  fi
  if ! gosu appuser:appgroup sh -c "touch \"$dir/.write_probe\" 2>/dev/null && rm -f \"$dir/.write_probe\""; then
    echo "entrypoint: fixing ownership of $dir -> appuser:appgroup"
    chown -R appuser:appgroup "$dir" || true
  fi
  if [ -d "$dir" ]; then
    for f in "$dir"/* "$dir"/.*; do
      [ -e "$f" ] || continue
      [ -f "$f" ] || continue
      case "$(basename "$f")" in .|..) continue ;; esac
      if ! gosu appuser:appgroup sh -c "test -w \"$f\"" 2>/dev/null; then
        echo "entrypoint: fixing file ownership $f -> appuser:appgroup"
        chown appuser:appgroup "$f" || true
        chmod ug+rw "$f" || true
      fi
    done
  fi
}

fix_data_dir /app/chroma
fix_data_dir /app/uploads
fix_data_dir /app/repos
fix_data_dir /app/uploads/chroma_knowledge
fix_data_dir /app/updates
fix_data_dir /app/hf_cache
fix_data_dir /app/certs
fix_data_dir /prometheus/targets
fix_data_dir /etc/prometheus/targets

if [ "$(id -u)" -eq 0 ] && [ -S /var/run/docker.sock ]; then
  SOCK_GID="$(stat -c '%g' /var/run/docker.sock 2>/dev/null || true)"
  if [ -n "$SOCK_GID" ] && [ "$SOCK_GID" != "0" ]; then
    if ! getent group "$SOCK_GID" >/dev/null 2>&1; then
      groupadd -g "$SOCK_GID" dockersock 2>/dev/null || true
    fi
    GRP_NAME="$(getent group "$SOCK_GID" | cut -d: -f1 || echo dockersock)"
    usermod -aG "$GRP_NAME" appuser 2>/dev/null || true
    echo "entrypoint: appuser → group $GRP_NAME (docker.sock gid=$SOCK_GID)"
  fi
fi

PROCESS_ENV_FILE="${PROCESS_WORKERS_ENV_FILE:-/app/uploads/ainew_process_workers.env}"
if [ -f "$PROCESS_ENV_FILE" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      \#*|"") continue ;;
      UVICORN_WORKERS=*)
        export UVICORN_WORKERS="${line#UVICORN_WORKERS=}"
        ;;
      CELERY_CONCURRENCY=*)
        export CELERY_CONCURRENCY="${line#CELERY_CONCURRENCY=}"
        ;;
    esac
  done < "$PROCESS_ENV_FILE"
  echo "entrypoint: process workers from $PROCESS_ENV_FILE (UVICORN_WORKERS=${UVICORN_WORKERS:-} CELERY_CONCURRENCY=${CELERY_CONCURRENCY:-})"
fi

# uvicorn / celery: env’deki worker sayısını zorla
if [ "$1" = "uvicorn" ]; then
  W="${UVICORN_WORKERS:-1}"
  case "$W" in ''|*[!0-9]*) W=1 ;; esac
  [ "$W" -lt 1 ] && W=1
  # Chroma PersistentClient (DuckDB) process-safe değil — 2+ uvicorn worker
  # aynı chroma yolunda kilit / zombie worker / tüm API'nin ölmesine yol açar.
  if [ "$W" -gt 1 ]; then
    echo "entrypoint: UVICORN_WORKERS=$W → 1 (Chroma tek-process; 2+ worker API'yi kilitler)"
    W=1
  fi
  ARGS=""
  SKIP=0
  for a in "$@"; do
    if [ "$SKIP" = 1 ]; then SKIP=0; continue; fi
    case "$a" in
      --workers) SKIP=1; continue ;;
      --workers=*) continue ;;
    esac
    ARGS="$ARGS $a"
  done
  # shellcheck disable=SC2086
  set -- $ARGS --workers "$W"
  echo "entrypoint: uvicorn workers=$W"
elif [ "$1" = "celery" ]; then
  C="${CELERY_CONCURRENCY:-2}"
  case "$C" in ''|*[!0-9]*) C=2 ;; esac
  [ "$C" -lt 1 ] && C=1
  [ "$C" -gt 32 ] && C=32
  ARGS=""
  SKIP=0
  for a in "$@"; do
    if [ "$SKIP" = 1 ]; then SKIP=0; continue; fi
    case "$a" in
      --concurrency)
        SKIP=1
        continue
        ;;
      --concurrency=*)
        continue
        ;;
    esac
    ARGS="$ARGS $a"
  done
  # shellcheck disable=SC2086
  set -- $ARGS --concurrency "$C"
  echo "entrypoint: celery concurrency=$C"
fi

if [ "$(id -u)" -eq 0 ]; then
  exec gosu appuser "$@"
fi
exec "$@"
