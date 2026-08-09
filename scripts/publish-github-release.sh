#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# publish-github-release.sh
#
# release.sh / build-distribution.sh ile üretilmiş dist/*.tar.gz paketini
# GitHub'a tag + Release olarak gönderir. İmaj DERLEMEZ / tar yeniden üretmez.
#
# Kullanım:
#   ./scripts/publish-github-release.sh
#   ./scripts/publish-github-release.sh 1.0.9.22
#   ./scripts/publish-github-release.sh 1.0.9.22 --with-ollama
#   ./scripts/publish-github-release.sh --notes-file /tmp/ainew-release-notes-1.0.9.22.txt
#
# Önkoşullar:
#   - Geçerli git repo (.git/HEAD + config)
#   - gh auth login
#   - dist/ainew-<ver>-linux-amd64.tar.gz hazır (veya --with-ollama)
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

WITH_OLLAMA=0
NOTES_FILE=""
VERSION_ARG=""
REPO_DEFAULT="datatemteknoloji/ai_eyup"
# Varsayılan: sadece sürüm/paketleme dosyaları (çalışma ağacındaki toplu silmeleri commit etmez)
COMMIT_ALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-ollama|--bundle-ollama) WITH_OLLAMA=1; shift ;;
    --notes-file) NOTES_FILE="$2"; shift 2 ;;
    --repo) REPO_DEFAULT="$2"; shift 2 ;;
    --all-changes) COMMIT_ALL=1; shift ;;
    -h|--help)
      sed -n '2,22p' "$0"
      exit 0
      ;;
    *)
      if [[ -z "$VERSION_ARG" && "$1" != -* ]]; then
        VERSION_ARG="$1"
        shift
      else
        echo "Bilinmeyen argüman: $1" >&2
        exit 1
      fi
      ;;
  esac
done

c_green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red() { printf '\033[0;31m%s\033[0m\n' "$1"; }
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

# ── 0. Önkoşullar ───────────────────────────────────────────────────────────
step "Önkoşullar kontrol ediliyor"

if [[ ! -d .git || ! -f .git/HEAD || ! -f .git/config ]]; then
  c_red "Geçerli git deposu yok (.git/HEAD veya .git/config eksik)."
  c_yellow "Eski sunucudan .git kopyasının tamamlandığından emin olun."
  exit 1
fi

# root ile çalışırken "dubious ownership" engelini kaldır
git config --global --add safe.directory "$ROOT_DIR" 2>/dev/null || true

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  c_red "git rev-parse başarısız — .git bozuk veya eksik olabilir."
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  c_red "gh CLI yok."
  exit 1
fi

if ! gh auth status -h github.com >/dev/null 2>&1; then
  c_red "gh oturumu yok veya token geçersiz."
  c_yellow "Çalıştırın: gh auth login -h github.com"
  gh auth status -h github.com 2>&1 || true
  exit 1
fi

VERSION="${VERSION_ARG:-$(tr -d '[:space:]' < VERSION 2>/dev/null || true)}"
if [[ -z "$VERSION" ]]; then
  c_red "VERSION boş. Kullanım: $0 <version>"
  exit 1
fi
TAG="v${VERSION}"

if [[ "$WITH_OLLAMA" -eq 1 ]]; then
  TAR="dist/ainew-${VERSION}-linux-amd64-with-ollama.tar.gz"
else
  TAR="dist/ainew-${VERSION}-linux-amd64.tar.gz"
fi
SHA="${TAR}.sha256"

if [[ ! -f "$TAR" ]]; then
  c_red "Paket bulunamadı: $TAR"
  c_yellow "Önce ollamasız paket: ./scripts/build-distribution.sh"
  c_yellow " veya: ./scripts/release.sh ${VERSION} \"özet\""
  exit 1
fi
if [[ ! -f "$SHA" ]]; then
  c_yellow "sha256 yok — üretiliyor: $SHA"
  sha256sum "$TAR" > "$SHA"
fi

if [[ -z "$NOTES_FILE" ]]; then
  NOTES_FILE="/tmp/ainew-release-notes-${VERSION}.txt"
fi
if [[ ! -s "$NOTES_FILE" ]]; then
  {
    echo "ainew ${VERSION} — offline kurulum paketi."
    if [[ "$WITH_OLLAMA" -eq 0 ]]; then
      echo "Ollama dahil değildir."
    else
      echo "Ollama + embedding modeli pakete gömülüdür."
    fi
  } > "$NOTES_FILE"
fi

REMOTE="origin"
if ! git remote get-url origin >/dev/null 2>&1; then
  if git remote get-url ai_eyup >/dev/null 2>&1; then
    REMOTE="ai_eyup"
    c_yellow "origin yok — remote olarak 'ai_eyup' kullanılacak."
  else
    first="$(git remote 2>/dev/null | head -1 || true)"
    if [[ -n "$first" ]]; then
      REMOTE="$first"
      c_yellow "origin yok — remote olarak '${REMOTE}' kullanılacak."
    else
      c_yellow "Remote yok — HTTPS origin ekleniyor: https://github.com/${REPO_DEFAULT}.git"
      git remote add origin "https://github.com/${REPO_DEFAULT}.git"
      REMOTE="origin"
    fi
  fi
fi

# gh HTTPS token ile push kolay olsun: SSH remote ise HTTPS'e çevir (yalnızca bu koşu için değil, kalıcı)
REMOTE_URL="$(git remote get-url "$REMOTE")"
if [[ "$REMOTE_URL" == git@github.com:* ]]; then
  HTTPS_URL="https://github.com/${REMOTE_URL#git@github.com:}"
  HTTPS_URL="${HTTPS_URL%.git}.git"
  c_yellow "SSH remote → HTTPS (gh token ile push): ${HTTPS_URL}"
  git remote set-url "$REMOTE" "$HTTPS_URL"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
if [[ "$BRANCH" == "HEAD" ]]; then
  if git show-ref --verify --quiet refs/heads/main; then
    BRANCH="main"
  elif git show-ref --verify --quiet refs/heads/master; then
    BRANCH="master"
  else
    BRANCH="main"
  fi
  c_yellow "Detached HEAD — push hedefi: ${BRANCH}"
fi

c_green "Sürüm : ${VERSION} (${TAG})"
c_green "Paket : ${TAR} ($(du -h "$TAR" | awk '{print $1}'))"
c_green "Branch: ${BRANCH}"
c_green "Remote: ${REMOTE} ($(git remote get-url "$REMOTE"))"

# ── 1. Commit ───────────────────────────────────────────────────────────────
step "Değişiklikler commit ediliyor (.env / dist tar hariç)"

if [[ "$COMMIT_ALL" -eq 1 ]]; then
  c_yellow "--all-changes: tüm tracked değişiklikler eklenecek (dikkat!)."
  git add -A 2>/dev/null || true
else
  # Güvenli varsayılan — bu sunucudaki eksik dosya silmelerini main'e basma
  for path in \
      VERSION CHANGELOG.md README.md .gitignore .env.example \
      deploy scripts \
      docker-compose.prod.yml docker-compose.build.yml docker-compose.dropt.yml \
      install-rhel.sh update-rhel.sh rollback-rhel.sh \
      ainew-apply-update.sh fix-load-ainew-images.sh install-ollama-runtime.sh \
      backend/VERSION; do
    if [[ -e "$path" ]] || git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
      git add -A -- "$path" 2>/dev/null || git add -- "$path" 2>/dev/null || true
    fi
  done
fi

# Hassas / büyük dosyaları staging'den çıkar
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  git reset HEAD -- "$f" >/dev/null 2>&1 || true
done < <(git diff --cached --name-only 2>/dev/null | grep -E '(^|/)\.env($|\.|/)|(^|/)dist/.*\.tar\.gz(\.sha256)?$|node_modules/' || true)

if git diff --cached --quiet 2>/dev/null; then
  c_yellow "Commitlenecek staged değişiklik yok — atlanıyor."
else
  echo "Staged dosyalar:"
  git diff --cached --name-only | sed 's/^/  /' | head -80
  git commit -m "chore(release): v${VERSION}"
  c_green "Commit: chore(release): v${VERSION}"
fi

# ── 2. Tag ──────────────────────────────────────────────────────────────────
step "Tag: ${TAG}"
if git rev-parse "$TAG" >/dev/null 2>&1; then
  c_yellow "Yerel tag zaten var: ${TAG}"
else
  git tag "$TAG"
  c_green "Tag oluşturuldu: ${TAG}"
fi

# ── 3. Push ─────────────────────────────────────────────────────────────────
step "git push (branch + tag)"
# gh credential helper — HTTPS push için
if command -v gh >/dev/null 2>&1; then
  gh auth setup-git -h github.com 2>/dev/null || true
fi
git push -u "$REMOTE" "HEAD:refs/heads/${BRANCH}"
git push "$REMOTE" "$TAG"
c_green "Push tamam."

# ── 4. GitHub Release ───────────────────────────────────────────────────────
step "GitHub Release: ${TAG}"

ASSETS=("$TAR" "$SHA")

if gh release view "$TAG" --repo "$REPO_DEFAULT" >/dev/null 2>&1; then
  c_yellow "Release mevcut — asset'ler güncelleniyor..."
  gh release upload "$TAG" "${ASSETS[@]}" --repo "$REPO_DEFAULT" --clobber
else
  gh release create "$TAG" "${ASSETS[@]}" \
    --repo "$REPO_DEFAULT" \
    --target "$BRANCH" \
    --title "ainew ${VERSION}" \
    --notes-file "$NOTES_FILE"
fi

echo
c_green "════════════════════════════════════════════════════════════════"
c_green " Yayın tamam: ${TAG}"
c_green "════════════════════════════════════════════════════════════════"
echo " Release: https://github.com/${REPO_DEFAULT}/releases/tag/${TAG}"
echo " Kontrol: gh release view ${TAG} --repo ${REPO_DEFAULT}"
echo
