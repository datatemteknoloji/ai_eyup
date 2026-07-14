#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Müşteri dağıtım paketi oluşturucu.
#
# Tracked kaynaktan (backend/, frontend/, prometheus/, deploy/, .env.example)
# reproducible bir `dist/ainew-<version>-<platform>/` paketi üretir. Bu makine
# (geliştirme ortamı) hangi CPU mimarisinde olursa olsun, varsayılan olarak
# linux/amd64 (tipik RHEL sunucu mimarisi) için imaj üretir — Docker Buildx +
# QEMU emülasyonu ile cross-build yapılır.
#
# Kullanım:
#   ./scripts/build-distribution.sh                 # linux/amd64 (varsayılan)
#   ./scripts/build-distribution.sh --platform linux/arm64
#   ./scripts/build-distribution.sh --no-images      # sadece kaynak paketi (registry/GitHub akışı için)
#
# Çıktı:
#   dist/ainew-<version>-<platform>.tar.gz
#     ├── docker-compose.prod.yml, install-rhel.sh, update-rhel.sh, rollback-rhel.sh
#     ├── frontend/nginx.prod.conf                    (deploy/ içinden kopyalanır)
#     ├── (tüm kaynak kod: backend/, frontend/, prometheus/, docs/, ...)
#     └── images/*.tar.gz   (docker load ile yüklenecek önceden derlenmiş imajlar;
#                             90MB üstü olanlar .part01/.part02/... şeklinde
#                             parçalanır — GitHub'ın LFS'siz 100MB sınırı için;
#                             install-rhel.sh kurulumdan önce otomatik birleştirir)
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="$(cat VERSION 2>/dev/null || echo "0.0.0")"
PLATFORM="linux/amd64"
BUILD_IMAGES=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform) PLATFORM="$2"; shift 2 ;;
    --no-images) BUILD_IMAGES=0; shift ;;
    *) echo "Bilinmeyen argüman: $1"; exit 1 ;;
  esac
done

PLATFORM_TAG="${PLATFORM//\//-}"   # linux/amd64 -> linux-amd64
STAGE="dist/ainew-${VERSION}-${PLATFORM_TAG}"
IMAGES_DIR="${STAGE}/images"

echo "▶ Sürüm      : ${VERSION}"
echo "▶ Platform   : ${PLATFORM}"
echo "▶ Hedef      : ${STAGE}.tar.gz"

rm -rf "$STAGE"
mkdir -p "$STAGE" "$IMAGES_DIR"

# ── 1. Kaynak ağacını kopyala (dev/internal dosyalar hariç) ─────────────────
echo "▶ Kaynak kopyalanıyor..."
rsync -a \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude '.gstack/' \
  --exclude '.cursor*' \
  --exclude 'node_modules/' \
  --exclude 'frontend/node_modules/' \
  --exclude 'frontend/dist/' \
  --exclude 'frontend/.vite/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '.env' \
  --exclude 'dist/' \
  --exclude 'ainew/' \
  --exclude 'canvas/' \
  --exclude 'backend_temp/' \
  --exclude 'deploy/' \
  --exclude 'transcript_*.jsonl' \
  --exclude 'db_dump_*.sql' \
  --exclude '*.docx' \
  --exclude 'sync_from_spv.sh' \
  --exclude 'master_sync.sh' \
  --exclude 'generate_project_doc.py' \
  --exclude 'test_ssh.py' \
  --exclude '/Dockerfile' \
  --exclude 'CLAUDE.md' \
  --exclude 'TESTING.md' \
  --exclude 'DETAYLI_AUDIT_RAPORU.md' \
  --exclude 'DUZELTMELER_OZET.md' \
  --exclude 'AI_CHAT_OZET.md' \
  --exclude 'AI_MODEL_ANALIZ.md' \
  --exclude 'MODEL_SECIMI.md' \
  --exclude 'PROJECT_CONTEXT.md' \
  --exclude 'PROJE_OZETI.md' \
  --exclude 'backend/static/node_exporter/arm64/' \
  --exclude 'backend/static/node_exporter/armv7/' \
  ./ "$STAGE"/

# ── 2. Production deployment varlıklarını deploy/ içinden yerleştir ─────────
# docker-compose.prod.yml ve install-rhel.sh, paket kökünde (./backend,
# ./frontend, ./prometheus ile aynı seviyede) olmalı çünkü bind mount yolları
# bunlara görecelidir.
echo "▶ Production dağıtım varlıkları yerleştiriliyor (deploy/)..."
cp deploy/docker-compose.prod.yml "$STAGE/docker-compose.prod.yml"
cp deploy/docker-compose.build.yml "$STAGE/docker-compose.build.yml"
cp deploy/install-rhel.sh "$STAGE/install-rhel.sh"
cp deploy/update-rhel.sh "$STAGE/update-rhel.sh"
cp deploy/rollback-rhel.sh "$STAGE/rollback-rhel.sh"
cp deploy/nginx.prod.conf "$STAGE/frontend/nginx.prod.conf"
chmod +x "$STAGE/install-rhel.sh" "$STAGE/update-rhel.sh" "$STAGE/rollback-rhel.sh"

# Müşteriye özel/gerçek sunucu verisi içeren dosyaları boş şablonla değiştir
echo "[]" > "$STAGE/prometheus/targets/node_exporter_targets.json"
echo "[]" > "$STAGE/prometheus/targets/windows_exporter_targets.json"

# ── 3. İmajları derle / çek / kaydet ────────────────────────────────────────
if [[ "$BUILD_IMAGES" -eq 1 ]]; then
  if ! docker buildx inspect dist-builder >/dev/null 2>&1; then
    docker buildx create --name dist-builder --use >/dev/null
  else
    docker buildx use dist-builder
  fi

  # --provenance=false --sbom=false: buildx varsayılan olarak ek attestation/SBOM
  # manifestleri üretir; bu bazı Docker sürümlerinde (containerd image store ile)
  # "docker save" işlemini "content digest not found" hatasıyla bozar.
  echo "▶ Backend imajı derleniyor (${PLATFORM})..."
  # Sürüm bilgisini imaja göm (UI /health / public API)
  cp -f VERSION backend/VERSION 2>/dev/null || true
  docker buildx build --platform "$PLATFORM" --provenance=false --sbom=false \
    --build-arg "APP_VERSION=${VERSION}" \
    -t "ainew-backend:${VERSION}" --load ./backend

  echo "▶ Frontend imajı derleniyor (${PLATFORM})..."
  docker buildx build --platform "$PLATFORM" --provenance=false --sbom=false \
    -t "ainew-frontend:${VERSION}" --load ./frontend

  # Not: Docker'ın containerd content-store'u ile çok mimarili (multi-arch) upstream
  # imajlarını doğrudan "docker pull --platform + docker save" ile kaydetmek bazı
  # Docker sürümlerinde "content digest not found" hatası veriyor. Çözüm: buildx ile
  # tek satırlık bir Dockerfile üzerinden hedef platforma "repack" edip öyle kaydet
  # (kendi imajlarımızda bu sorun yok, sadece upstream imajlarda gerekiyor).
  repack_and_save() {
    local src_image="$1" out_file="$2"
    local tmp_ctx
    tmp_ctx="$(mktemp -d)"
    printf 'FROM %s\n' "$src_image" > "${tmp_ctx}/Dockerfile"
    local tmp_tag="repack-tmp:$(echo "$src_image" | tr '/:' '--')"
    docker buildx build --platform "$PLATFORM" --provenance=false --sbom=false -t "$tmp_tag" --load "$tmp_ctx" >/dev/null

    # Bu build makinesi ${PLATFORM} dışında bir mimaride (ör. arm64 geliştirme
    # ortamı) olabilir ve "$src_image" etiketi zaten yerel olarak native mimaride
    # kullanılıyor olabilir (ör. bu makinedeki çalışan dev stack). docker-compose.prod.yml
    # orijinal imaj adını (ör. timescale/timescaledb:2.17.2-pg15) referans aldığı için
    # tar içine o adla kaydetmemiz gerekiyor — ama işlem bitince orijinal yerel etiketi
    # geri yükleyip bu build makinesindeki mevcut imajları bozmadan bırakıyoruz.
    local orig_id
    orig_id="$(docker image inspect -f '{{.Id}}' "$src_image" 2>/dev/null || true)"

    docker tag "$tmp_tag" "$src_image"
    docker save "$src_image" | gzip > "$out_file"

    if [[ -n "$orig_id" ]]; then
      docker tag "$orig_id" "$src_image"   # native mimarideki orijinal etiketi geri yükle
    else
      docker rmi "$src_image" >/dev/null 2>&1 || true
    fi
    docker rmi "$tmp_tag" >/dev/null 2>&1 || true
    rm -rf "$tmp_ctx"
  }

  echo "▶ Üçüncü parti imajlar hazırlanıyor (${PLATFORM})..."
  echo "▶ İmajlar kaydediliyor (docker save)..."
  docker save "ainew-backend:${VERSION}" | gzip > "${IMAGES_DIR}/ainew-backend.tar.gz"
  docker save "ainew-frontend:${VERSION}" | gzip > "${IMAGES_DIR}/ainew-frontend.tar.gz"
  repack_and_save "timescale/timescaledb:2.17.2-pg15" "${IMAGES_DIR}/timescaledb.tar.gz"
  repack_and_save "redis:7-alpine" "${IMAGES_DIR}/redis.tar.gz"
  repack_and_save "prom/prometheus:v2.55.1" "${IMAGES_DIR}/prometheus.tar.gz"
  repack_and_save "prom/pushgateway:v1.11.0" "${IMAGES_DIR}/pushgateway.tar.gz"

  # install-rhel.sh / docker-compose.prod.yml varsayılan olarak ":latest" imaj adı
  # bekler; offline pakette versiyon etiketli imajı "latest" olarak da işaretleyelim
  # ki docker-compose.prod.yml değişmeden çalışsın.
  cat >> "$STAGE/.env.example" <<EOF

# build-distribution.sh tarafından üretildi — bu paketteki imaj etiketleri
BACKEND_IMAGE=ainew-backend:${VERSION}
FRONTEND_IMAGE=ainew-frontend:${VERSION}
EOF

  # GitHub'ın LFS'siz push'larda uyguladığı 100MB/dosya sert sınırı nedeniyle,
  # bu paket git'e commit edilecekse (ör. tamamen air-gapped hedeflere "git clone /
  # Download ZIP" ile taşınacaksa) 90MB'ı aşan imaj arşivleri parçalara bölünür.
  # install-rhel.sh, kurulumdan önce bu parçaları otomatik olarak geri birleştirir
  # (bkz. "Parçalanmış imaj arşivleri birleştiriliyor" adımı). scp/USB ile doğrudan
  # taşıyanlar için bu bölme gereksizdir ama zararsızdır (install-rhel.sh her durumda
  # doğru çalışır).
  echo "▶ 90MB üstü imaj arşivleri git-uyumlu parçalara bölünüyor..."
  for f in "$IMAGES_DIR"/*.tar.gz; do
    [[ -e "$f" ]] || continue
    size="$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f")"
    if (( size > 94371840 )); then
      split -b 90m -d --numeric-suffixes=01 "$f" "${f}.part"
      rm -f "$f"
      echo "  ✂ $(basename "$f") -> $(basename "$f").part01, .part02, ..."
    fi
  done
else
  echo "▶ --no-images verildi, imaj derleme/kaydetme atlandı (kaynak koddan derlenecek)."
fi

# ── 4. Arşivle ───────────────────────────────────────────────────────────────
echo "▶ Arşivleniyor..."
tar -C dist -czf "${STAGE}.tar.gz" "$(basename "$STAGE")"
sha256sum "${STAGE}.tar.gz" > "${STAGE}.tar.gz.sha256"
du -sh "${STAGE}.tar.gz"

echo
echo "✔ Paket hazır: ${STAGE}.tar.gz"
echo "  İlk kurulum:"
echo "    tar xzf $(basename "${STAGE}.tar.gz") && cd $(basename "$STAGE") && sudo ./install-rhel.sh"
echo "  Güncelleme:"
echo "    tar xzf $(basename "${STAGE}.tar.gz") && cd $(basename "$STAGE")"
echo "    sudo ./update-rhel.sh --install-dir /opt/ainew"
echo "  Geri alma:"
echo "    cd /opt/ainew && sudo ./rollback-rhel.sh"
