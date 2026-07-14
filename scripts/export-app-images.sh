#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Sadece uygulama imajlarını dışa aktarır (Timescale/Redis/Prometheus YOK).
#
# Çıktı:
#   dist/ainew-<VERSION>-app-images/
#     ainew-backend.tar.gz[.partXX]
#     ainew-frontend.tar.gz
#     load.sh          — hedef sunucuda: sudo ./load.sh
#     README.md
#   dist/ainew-<VERSION>-app-images.tar.gz  — tek dosya (scp için; git'e girmez)
#
# Kullanım:
#   ./scripts/export-app-images.sh              # VERSION dosyasından
#   ./scripts/export-app-images.sh 1.0.9
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${1:-$(cat VERSION 2>/dev/null || echo "0.0.0")}"
BACKEND_TAG="ainew-backend:${VERSION}"
FRONTEND_TAG="ainew-frontend:${VERSION}"
OUT_DIR="dist/ainew-${VERSION}-app-images"

if ! docker image inspect "$BACKEND_TAG" >/dev/null 2>&1; then
  echo "Hata: $BACKEND_TAG yok. Önce: ./scripts/build-distribution.sh" >&2
  exit 1
fi
if ! docker image inspect "$FRONTEND_TAG" >/dev/null 2>&1; then
  echo "Hata: $FRONTEND_TAG yok. Önce: ./scripts/build-distribution.sh" >&2
  exit 1
fi

echo "▶ Uygulama imajları: $BACKEND_TAG + $FRONTEND_TAG"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

echo "▶ docker save..."
docker save "$BACKEND_TAG" | gzip > "${OUT_DIR}/ainew-backend.tar.gz"
docker save "$FRONTEND_TAG" | gzip > "${OUT_DIR}/ainew-frontend.tar.gz"

# GitHub 100MB sınırı için gerekirse parçala
echo "▶ 90MB üstü arşivler parçalanıyor (git/GitHub uyumu)..."
for f in "$OUT_DIR"/*.tar.gz; do
  [[ -e "$f" ]] || continue
  size="$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f")"
  if (( size > 94371840 )); then
    split -b 90m -d --numeric-suffixes=01 "$f" "${f}.part"
    rm -f "$f"
    echo "  ✂ $(basename "$f") -> $(basename "$f").part01, .part02, ..."
  fi
done

cat > "${OUT_DIR}/load.sh" <<EOF
#!/usr/bin/env bash
# ainew ${VERSION} — sadece uygulama imajlarını yükler (DB/Redis ayrı kalır)
set -euo pipefail
cd "\$(dirname "\$0")"

join_parts() {
  local base="\$1"
  if [[ -f "\${base}" ]]; then
    echo "\${base}"
    return
  fi
  if compgen -G "\${base}.part*" > /dev/null; then
    cat \${base}.part* > "\${base}"
    echo "\${base}"
    return
  fi
  echo "Bulunamadı: \${base}" >&2
  exit 1
}

echo "▶ ainew-backend:${VERSION} yükleniyor..."
BE=\$(join_parts ainew-backend.tar.gz)
gunzip -c "\$BE" | docker load
echo "▶ ainew-frontend:${VERSION} yükleniyor..."
FE=\$(join_parts ainew-frontend.tar.gz)
gunzip -c "\$FE" | docker load

docker tag "ainew-backend:${VERSION}" ainew-backend:latest
docker tag "ainew-frontend:${VERSION}" ainew-frontend:latest

echo
echo "✔ Yüklendi:"
docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -E 'ainew-(backend|frontend):(latest|${VERSION})' || true
echo
echo "Mevcut kurulumda .env:"
echo "  APP_VERSION=${VERSION}"
echo "  BACKEND_IMAGE=ainew-backend:${VERSION}"
echo "  FRONTEND_IMAGE=ainew-frontend:${VERSION}"
echo "Ardından: docker compose -f docker-compose.prod.yml up -d backend frontend"
EOF
chmod +x "${OUT_DIR}/load.sh"

cat > "${OUT_DIR}/README.md" <<EOF
# ainew ${VERSION} — uygulama imajları

Bu paket **sadece** uygulama imajlarını içerir:

- \`ainew-backend:${VERSION}\`
- \`ainew-frontend:${VERSION}\`

TimescaleDB / Redis / Prometheus **yoktur** (mevcut sunucuda kalır veya Docker Hub'dan çekilir).

## Yükleme

\`\`\`bash
cd ainew-${VERSION}-app-images
sudo ./load.sh
\`\`\`

## Mevcut kurulumda güncelleme

\`/opt/ainew/.env\` içinde:

\`\`\`
APP_VERSION=${VERSION}
BACKEND_IMAGE=ainew-backend:${VERSION}
FRONTEND_IMAGE=ainew-frontend:${VERSION}
\`\`\`

\`\`\`bash
cd /opt/ainew
docker compose -f docker-compose.prod.yml up -d backend frontend
\`\`\`
EOF

# Tek dosyalık arşiv (scp/USB — gitignore'da dist/*.tar.gz)
BUNDLE="dist/ainew-${VERSION}-app-images.tar.gz"
tar -C dist -czf "$BUNDLE" "ainew-${VERSION}-app-images"
echo "▶ Paket: $BUNDLE ($(du -h "$BUNDLE" | cut -f1))"
echo "▶ Klasör: $OUT_DIR"
ls -lh "$OUT_DIR"
echo "✔ Tamam"
