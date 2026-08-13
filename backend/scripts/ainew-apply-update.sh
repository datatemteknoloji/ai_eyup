#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# GUI platform güncelleme wrapper'ı — host üzerinde (nsenter ile) çalışır.
# Backend ayrık updater container başlatır; bu betik status.json yazar ve
# update-rhel.sh / rollback-rhel.sh çağırır.
#
# Kullanım:
#   ainew-apply-update.sh apply  <pkg_dir>
#   ainew-apply-update.sh rollback [--restore-db]
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

ACTION="${1:-}"
shift || true

INSTALL_DIR="${AINEW_INSTALL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DATA_DIR="${AINEW_DATA_DIR:-$INSTALL_DIR/data}"
UPDATES_DIR="${DATA_DIR}/updates"
STATUS_FILE="${UPDATES_DIR}/status.json"
LOG_FILE="${UPDATES_DIR}/apply.log"

mkdir -p "$UPDATES_DIR"
: > "$LOG_FILE"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

write_status() {
  local state="$1" old_v="${2:-}" new_v="${3:-}" msg="${4:-}"
  cat > "$STATUS_FILE" <<EOF
{
  "state": "$(printf '%s' "$state" | sed 's/"/\\"/g')",
  "action": "$(printf '%s' "${ACTION:-}" | sed 's/"/\\"/g')",
  "old_version": "$(printf '%s' "$old_v" | sed 's/"/\\"/g')",
  "new_version": "$(printf '%s' "$new_v" | sed 's/"/\\"/g')",
  "message": "$(printf '%s' "$msg" | sed 's/"/\\"/g')",
  "updated_at": "$(ts)",
  "log_file": "$LOG_FILE"
}
EOF
}

tail_log() {
  if [[ -f "$LOG_FILE" ]]; then
    tail -n 40 "$LOG_FILE" 2>/dev/null || true
  fi
}

log() { printf '%s %s\n' "$(ts)" "$*" | tee -a "$LOG_FILE"; }

OLD_VERSION="$(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo unknown)"

case "$ACTION" in
  apply)
    PKG_DIR="${1:-}"
    if [[ -z "$PKG_DIR" || ! -d "$PKG_DIR" ]]; then
      write_status "failed" "$OLD_VERSION" "" "Paket dizini yok: $PKG_DIR"
      exit 1
    fi
    if [[ ! -f "$PKG_DIR/update-rhel.sh" ]]; then
      write_status "failed" "$OLD_VERSION" "" "update-rhel.sh bulunamadı"
      exit 1
    fi
    NEW_VERSION="$(cat "$PKG_DIR/VERSION" 2>/dev/null || echo unknown)"
    write_status "running" "$OLD_VERSION" "$NEW_VERSION" "Güncelleme başlatıldı"
    log "apply: $OLD_VERSION → $NEW_VERSION pkg=$PKG_DIR install=$INSTALL_DIR"

    chmod +x "$PKG_DIR/update-rhel.sh" 2>/dev/null || true
    set +e
    (
      cd "$PKG_DIR"
      ./update-rhel.sh --install-dir "$INSTALL_DIR"
    ) >>"$LOG_FILE" 2>&1
    rc=$?
    set -e

    if [[ $rc -eq 0 ]]; then
      ACTUAL="$(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo "$NEW_VERSION")"
      write_status "success" "$OLD_VERSION" "$ACTUAL" "Güncelleme tamamlandı"
      log "apply success: $ACTUAL"
      exit 0
    fi
    write_status "failed" "$OLD_VERSION" "$NEW_VERSION" "update-rhel.sh exit=$rc"
    log "apply failed rc=$rc"
    exit "$rc"
    ;;

  rollback)
    EXTRA=()
    while [[ $# -gt 0 ]]; do
      EXTRA+=("$1"); shift
    done
    write_status "running" "$OLD_VERSION" "" "Geri alma başlatıldı"
    log "rollback: install=$INSTALL_DIR extras=${EXTRA[*]:-}"

    if [[ ! -f "$INSTALL_DIR/rollback-rhel.sh" ]]; then
      write_status "failed" "$OLD_VERSION" "" "rollback-rhel.sh bulunamadı"
      exit 1
    fi
    chmod +x "$INSTALL_DIR/rollback-rhel.sh" 2>/dev/null || true
    set +e
    (
      cd "$INSTALL_DIR"
      # GUI rollback DB dump restore etmez (onaysız yıkıcı); sadece imaj
      ./rollback-rhel.sh "${EXTRA[@]}"
    ) >>"$LOG_FILE" 2>&1
    rc=$?
    set -e

    NEW_V="$(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo unknown)"
    if [[ $rc -eq 0 ]]; then
      write_status "success" "$OLD_VERSION" "$NEW_V" "Geri alma tamamlandı"
      log "rollback success: $NEW_V"
      exit 0
    fi
    write_status "failed" "$OLD_VERSION" "$NEW_V" "rollback-rhel.sh exit=$rc"
    log "rollback failed rc=$rc"
    exit "$rc"
    ;;

  *)
    write_status "failed" "$OLD_VERSION" "" "Bilinmeyen action: $ACTION"
    echo "Kullanım: $0 apply <pkg_dir> | rollback" >&2
    exit 2
    ;;
esac
