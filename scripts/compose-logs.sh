#!/usr/bin/env bash
# Tüm servis loglarını Docker meta timestamp ile gösterir.
# Kullanım:
#   ./scripts/compose-logs.sh
#   ./scripts/compose-logs.sh -f backend frontend
#   ./scripts/compose-logs.sh --tail 100
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# -t : her satıra Docker zaman damgası (tüm konteynerler)
# Uygulama içi loglar da zaten kendi tarih-saatlerini içerir.
exec docker compose logs -t --tail "${COMPOSE_LOG_TAIL:-200}" "$@"
