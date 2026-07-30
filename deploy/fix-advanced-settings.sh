#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# "Gelişmiş ayarlar yüklenemedi" — KeyError: 'help' hotfix
#
# virt_chat_max_tool_steps şemasında eksik "help" alanı /settings/advanced
# endpoint'ini 500 yapıyordu. Bu betik çalışan backend konteynerindeki
# runtime_settings.py dosyasını yamar ve backend'i yeniden başlatır.
#
# Kullanım (kurulum sunucusunda):
#   sudo ./fix-advanced-settings.sh
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

c_green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red() { printf '\033[0;31m%s\033[0m\n' "$1"; }

CONTAINER="${BACKEND_CONTAINER:-}"
if [[ -z "$CONTAINER" ]]; then
  for name in server_management_backend ainew-backend-1 ainew_backend_1; do
    if docker ps --format '{{.Names}}' | grep -qx "$name"; then
      CONTAINER="$name"
      break
    fi
  done
fi
if [[ -z "$CONTAINER" ]]; then
  CONTAINER="$(docker ps --format '{{.Names}}' | grep -E 'backend' | head -1 || true)"
fi
if [[ -z "$CONTAINER" ]]; then
  c_red "Backend konteyneri bulunamadı. BACKEND_CONTAINER=... ile tekrar deneyin."
  docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
  exit 1
fi

c_yellow "Hedef konteyner: $CONTAINER"
TARGET="/app/app/services/runtime_settings.py"

if ! docker exec "$CONTAINER" test -f "$TARGET"; then
  c_red "Dosya yok: $TARGET"
  exit 1
fi

# Zaten düzeltilmiş mi?
if docker exec "$CONTAINER" grep -q 'Agentic sanallaştırma sohbetinde' "$TARGET" 2>/dev/null; then
  c_green "Yama zaten uygulanmış görünüyor."
else
  c_yellow "virt_chat_max_tool_steps için help alanı ekleniyor..."
  docker exec "$CONTAINER" python3 - <<'PY'
from pathlib import Path
path = Path("/app/app/services/runtime_settings.py")
text = path.read_text()
old = '''    "virt_chat_max_tool_steps": {
        "default": 4, "type": "int", "min": 1, "max": 8,
        "group": "virt_chat", "label": "Sanallaştırma Chat maks. araç adımı",
        "env": "VIRT_CHAT_MAX_TOOL_STEPS",
    },'''
new = '''    "virt_chat_max_tool_steps": {
        "default": 4, "type": "int", "min": 1, "max": 8,
        "group": "virt_chat", "label": "Sanallaştırma Chat maks. araç adımı",
        "help": "Agentic sanallaştırma sohbetinde bir yanıt üretilmeden önce art arda "
                "çağrılabilecek en fazla vCenter READ_ONLY araç sayısı.",
        "env": "VIRT_CHAT_MAX_TOOL_STEPS",
    },'''
if old not in text:
    # Defensive .get already enough if schema differs — still harden list_advanced_settings
    if 'meta.get("help"' in text or "meta.get('help'" in text:
        print("SCHEMA_BLOCK_NOT_FOUND_BUT_GET_OK")
    else:
        text2 = text.replace(
            '"help": meta["help"],',
            '"help": meta.get("help", ""),',
        ).replace(
            '"label": meta["label"],',
            '"label": meta.get("label", key),',
        )
        if text2 == text:
            raise SystemExit("PATCH_FAILED: beklenen blok bulunamadı")
        path.write_text(text2)
        print("PATCHED_GET_FALLBACK")
else:
    path.write_text(text.replace(old, new, 1))
    print("PATCHED_SCHEMA_HELP")
# Also harden list_advanced_settings if still using meta["help"]
text = path.read_text()
text2 = text.replace('"help": meta["help"],', '"help": meta.get("help", ""),')
text2 = text2.replace('"label": meta["label"],', '"label": meta.get("label", key),')
if text2 != text:
    path.write_text(text2)
    print("PATCHED_GET_FALLBACK")
PY
fi

c_yellow "Backend yeniden başlatılıyor..."
docker restart "$CONTAINER" >/dev/null
sleep 6
c_green "Tamam. Ayarlar → Gelişmiş Ayarlar sayfasını yenileyin."
c_yellow "Kontrol: curl -sf http://127.0.0.1:8000/health && echo"
