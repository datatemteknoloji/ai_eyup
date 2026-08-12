#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# release.sh — Yeni bir sürüm yayınlar ve CHANGELOG.md'yi günceller.
#
# Şu ana kadar release'ler `gh release create` ile elle, CHANGELOG.md'ye hiç
# dokunulmadan yapılıyordu — bu da air-gapped (internetsiz) müşterilerin sürüm
# geçmişini görecek hiçbir yolu olmadığı anlamına geliyordu (devex-review
# bulgusu, 2026-08-02). Bu script GitHub Release notlarını CHANGELOG.md'ye de
# yazarak bu ikisinin senkron kalmasını sağlar.
#
# Kullanım:
#   ./scripts/release.sh 1.0.9.17 "Kısa özet satırı" [--with-ollama] [--no-images] [--no-publish]
#
#   --no-publish  VERSION/CHANGELOG/paket + yerel commit/tag; GitHub Release / push yok
#
# Notlar:
#   - CHANGELOG.md'deki [Unreleased] bölümü varsa, yeni sürüm başlığının
#     altına taşınır (böylece geliştirme sırasında CHANGELOG'a eklenen
#     maddeler kaybolmaz).
#   - VERSION dosyası güncellenir.
#   - dist/ paketi scripts/build-distribution.sh ile üretilir.
#   - Değişiklikler commit'lenir, git tag atılır, `gh release create` ile
#     CHANGELOG'daki AYNI metinle GitHub Release oluşturulur.
#   - `gh` CLI kurulu ve login olmuş olmalı (`gh auth status`).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${1:-}"
SUMMARY="${2:-}"
shift 2 || true

if [[ -z "$VERSION" || -z "$SUMMARY" ]]; then
  echo "Kullanım: $0 <version> \"<kısa özet>\" [build-distribution.sh argümanları] [--no-publish]" >&2
  echo "Örnek:    $0 1.0.9.17 \"vCenter timeout düzeltmesi\" --with-ollama" >&2
  exit 1
fi

NO_PUBLISH=0
BUILD_ARGS=()
for a in "$@"; do
  case "$a" in
    --no-publish) NO_PUBLISH=1 ;;
    *) BUILD_ARGS+=("$a") ;;
  esac
done
set -- "${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"}"

CHANGELOG="CHANGELOG.md"
TODAY="$(date +%Y-%m-%d)"

if [[ ! -f "$CHANGELOG" ]]; then
  echo "HATA: $CHANGELOG bulunamadı." >&2
  exit 1
fi

echo "▶ Sürüm: ${VERSION}  (${TODAY})"
echo "▶ Özet : ${SUMMARY}"

# 1) VERSION dosyasını güncelle
echo "$VERSION" > VERSION

# 2) CHANGELOG.md: [Unreleased] bölümünü [VERSION] - TARIH başlığına çevir
#    (madde listesi olduğu gibi korunur), üstüne boş yeni bir [Unreleased] ekle.
python3 - "$CHANGELOG" "$VERSION" "$TODAY" "$SUMMARY" <<'PYEOF'
import sys, re

path, version, today, summary = sys.argv[1:5]
text = open(path, encoding="utf-8").read()

marker = "## [Unreleased]"
idx = text.find(marker)
if idx == -1:
    print("UYARI: [Unreleased] bölümü bulunamadı, yeni bölüm en üste ekleniyor.", file=sys.stderr)
    header_end = text.find("\n\n") + 2
    new_section = f"## [{version}] - {today}\n\n{summary}\n\n"
    text = text[:header_end] + new_section + text[header_end:]
else:
    # [Unreleased] başlığından bir sonraki "## [" başlığına kadar olan içerik
    next_idx = text.find("\n## [", idx + len(marker))
    if next_idx == -1:
        next_idx = len(text)
    body = text[idx + len(marker):next_idx]
    new_block = f"{marker}\n\n## [{version}] - {today}\n\n{body.lstrip(chr(10))}"
    text = text[:idx] + new_block + text[next_idx:]

open(path, "w", encoding="utf-8").write(text)
print(f"✓ CHANGELOG.md güncellendi: [{version}] - {today}")
PYEOF

# 3) Release notlarını CHANGELOG'daki yeni bölümden çıkar (gh release body için)
#    Sabit bir yola yazılır (mktemp KULLANILMAZ) — script bittikten sonra da
#    `gh release create --notes-file` ile kullanılabilsin diye silinmez.
NOTES_FILE="/tmp/ainew-release-notes-${VERSION}.txt"
awk -v ver="[$VERSION]" '
  BEGIN{found=0}
  $0 ~ "^## \\" ver {found=1; next}
  found && /^## \[/ {exit}
  found {print}
' "$CHANGELOG" > "$NOTES_FILE"

echo "--- Release notu önizleme ---"
cat "$NOTES_FILE"
echo "-----------------------------"

# 4) Dağıtım paketini oluştur (varsa ekstra argümanlarla, örn. --with-ollama)
if [[ -x scripts/build-distribution.sh ]]; then
  ./scripts/build-distribution.sh "$@"
else
  echo "UYARI: scripts/build-distribution.sh bulunamadı, paket oluşturma adımı atlanıyor." >&2
fi

# 5) Commit + tag + push + GitHub Release (yeniden build YOK)
#    Ollama bayrağı verilmişse publish script'ine de iletilir.
PUBLISH_ARGS=("${VERSION}" --notes-file "${NOTES_FILE}")
for a in "$@"; do
  case "$a" in
    --with-ollama|--bundle-ollama) PUBLISH_ARGS+=("$a") ;;
  esac
done

if [[ "$NO_PUBLISH" -eq 1 ]]; then
  echo
  echo "▶ --no-publish: GitHub Release atlanıyor; VERSION/CHANGELOG commit + yerel tag."
  git add VERSION "$CHANGELOG"
  git commit -m "chore(release): v${VERSION}" || true
  git tag "v${VERSION}" 2>/dev/null || true
  echo "✓ Paket: dist/ainew-${VERSION}-linux-amd64*.tar.gz (varsa)"
  echo "  Notlar: ${NOTES_FILE}"
  echo "  Yayınlamak için: ./scripts/publish-github-release.sh ${VERSION} --notes-file '${NOTES_FILE}'"
elif [[ -x scripts/publish-github-release.sh ]]; then
  echo
  echo "▶ GitHub'a yayınlanıyor (scripts/publish-github-release.sh)..."
  ./scripts/publish-github-release.sh "${PUBLISH_ARGS[@]}"
else
  git add VERSION "$CHANGELOG"
  git commit -m "chore(release): v${VERSION}" || true
  git tag "v${VERSION}" 2>/dev/null || true
  echo
  echo "✓ Yerel commit/tag (publish script yok)."
  echo "  Push: git push && git push origin v${VERSION}"
  echo "  Release: gh release create v${VERSION} dist/ainew-${VERSION}-linux-amd64.tar.gz* --notes-file '${NOTES_FILE}' --title \"ainew ${VERSION}\""
fi
