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
#   ./scripts/build-distribution.sh --with-ollama    # + WITH_OLLAMA işareti (runtime kurulumda indirilir, ~+birkaç KB)
#   ./scripts/build-distribution.sh --bundle-ollama  # + ollama image + nomic-embed-text GÖMÜLÜ (~+3.5GB, tam offline)
#
# Ollama imajı + embedding modeli sabit, uygulama sürümünden BAĞIMSIZ bir GitHub
# release'te (ollama-runtime-v1) barınır — neredeyse hiç değişmezler. Varsayılan
# --with-ollama modu bunları pakete GÖMMEZ; install-rhel.sh/update-rhel.sh
# kurulum sırasında bir kereye mahsus indirip $DATA_DIR/.ollama-runtime-cache
# altına önbellekler (imaj zaten Docker'da / model zaten diskteyse hiç ağ
# erişimi gerekmez). Tam air-gapped hedefler için --bundle-ollama ile eski
# davranış (imaj+model paketin içine gömülü, internet gerekmez) kullanılabilir.
#
# Çıktı:
#   dist/ainew-<version>-<platform>.tar.gz
#   dist/ainew-<version>-<platform>-with-ollama.tar.gz   (--with-ollama / --bundle-ollama)
#     ├── docker-compose.yml   ← offline stack (deploy/docker-compose.prod.yml içeriği; standart ad)
#     ├── install-rhel.sh, update-rhel.sh, rollback-rhel.sh
#     ├── frontend/nginx.prod.conf                    (deploy/ içinden kopyalanır)
#     ├── (tüm kaynak kod: backend/, frontend/, prometheus/, docs/, ...)
#     ├── WITH_OLLAMA                                 (--with-ollama/--bundle-ollama işareti + runtime release bilgisi)
#     └── images/*.tar.gz   (docker load ile yüklenecek önceden derlenmiş imajlar;
#                             90MB üstü olanlar .part01/.part02/... şeklinde
#                             parçalanır — GitHub'ın LFS'siz 100MB sınırı için;
#                             install-rhel.sh kurulumdan önce otomatik birleştirir)
#                             --bundle-ollama: + ollama.tar.gz + ollama-models-nomic-embed-text.tar.gz
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="$(cat VERSION 2>/dev/null || echo "0.0.0")"
PLATFORM="linux/amd64"
BUILD_IMAGES=1
WITH_OLLAMA=0
BUNDLE_OLLAMA=0
EMBED_MODEL="${OLLAMA_EMBED_MODEL:-nomic-embed-text}"
# Ollama imajı + embedding modeli sabit, uygulama sürümünden bağımsız bir GitHub
# release'te barınır (nadiren değişir). --with-ollama paketi bunları GÖMMEZ,
# yalnızca install-rhel.sh/update-rhel.sh'in kurulum sırasında BİR KEREYE MAHSUS
# indirip önbellekleyeceği release'i işaret eder (bkz. WITH_OLLAMA dosyası).
# Tam air-gapped (internetsiz) hedefler için --bundle-ollama ile eski davranış
# (imaj+model paketin içine gömülür) hâlâ kullanılabilir.
OLLAMA_RUNTIME_RELEASE="${OLLAMA_RUNTIME_RELEASE:-ollama-runtime-v1}"
OLLAMA_RUNTIME_BASE_URL="${OLLAMA_RUNTIME_BASE_URL:-https://github.com/datatemteknoloji/ai_eyup/releases/download/${OLLAMA_RUNTIME_RELEASE}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform) PLATFORM="$2"; shift 2 ;;
    --no-images) BUILD_IMAGES=0; shift ;;
    --with-ollama) WITH_OLLAMA=1; shift ;;
    --bundle-ollama) WITH_OLLAMA=1; BUNDLE_OLLAMA=1; shift ;;
    --embed-model) EMBED_MODEL="$2"; shift 2 ;;
    *) echo "Bilinmeyen argüman: $1"; exit 1 ;;
  esac
done

PLATFORM_TAG="${PLATFORM//\//-}"   # linux/amd64 -> linux-amd64
STAGE="dist/ainew-${VERSION}-${PLATFORM_TAG}"
if [[ "$WITH_OLLAMA" -eq 1 ]]; then
  STAGE="${STAGE}-with-ollama"
fi
IMAGES_DIR="${STAGE}/images"

echo "▶ Sürüm      : ${VERSION}"
echo "▶ Platform   : ${PLATFORM}"
echo "▶ With Ollama: ${WITH_OLLAMA} (embed=${EMBED_MODEL})"
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
  --exclude 'data/' \
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
# Offline stack paket kökünde docker-compose.yml adıyla durur (standart compose
# dosya adı). rsync ile gelen geliştirme docker-compose.yml üzerine yazılır;
# docker-compose.prod.yml paketten kaldırılır (çift dosya karışıklığı olmasın).
echo "▶ Production dağıtım varlıkları yerleştiriliyor (deploy/)..."
cp deploy/docker-compose.prod.yml "$STAGE/docker-compose.yml"
rm -f "$STAGE/docker-compose.prod.yml"
cp deploy/docker-compose.build.yml "$STAGE/docker-compose.build.yml"
cp deploy/install-rhel.sh "$STAGE/install-rhel.sh"
cp deploy/update-rhel.sh "$STAGE/update-rhel.sh"
cp deploy/rollback-rhel.sh "$STAGE/rollback-rhel.sh"
cp deploy/ainew-apply-update.sh "$STAGE/ainew-apply-update.sh"
cp deploy/fix-load-ainew-images.sh "$STAGE/fix-load-ainew-images.sh"
cp deploy/install-ollama-runtime.sh "$STAGE/install-ollama-runtime.sh"
cp deploy/install-ollama-model.sh "$STAGE/install-ollama-model.sh" 2>/dev/null || true
cp deploy/nginx.prod.conf "$STAGE/frontend/nginx.prod.conf"
chmod +x "$STAGE/install-rhel.sh" "$STAGE/update-rhel.sh" "$STAGE/rollback-rhel.sh" \
  "$STAGE/ainew-apply-update.sh" "$STAGE/fix-load-ainew-images.sh" \
  "$STAGE/install-ollama-runtime.sh"
[[ -f "$STAGE/install-ollama-model.sh" ]] && chmod +x "$STAGE/install-ollama-model.sh"

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
  # RAG seed (docs/rag_seed) imaja göm — volume yoksa bile ilk açılışta chunk'lanır
  mkdir -p backend/docs/rag_seed
  if [[ -d docs/rag_seed ]]; then
    cp -a docs/rag_seed/. backend/docs/rag_seed/
  fi
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
    # kullanılıyor olabilir (ör. bu makinedeki çalışan dev stack). Paket docker-compose.yml
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
  echo "▶ Dropt API imajı derleniyor (Level 1 sidecar, ${PLATFORM})..."
  docker buildx build --platform "$PLATFORM" --provenance=false --sbom=false \
    -t "dropt-api:local" --load ./dropt/backend

  # compose varsayılanı :latest da arayabilsin diye aynı digest'e ikinci etiket
  docker tag "ainew-backend:${VERSION}" "ainew-backend:latest"
  docker tag "ainew-frontend:${VERSION}" "ainew-frontend:latest"

  echo "▶ İmajlar kaydediliyor (docker save)..."
  docker save "ainew-backend:${VERSION}" "ainew-backend:latest" | gzip > "${IMAGES_DIR}/ainew-backend.tar.gz"
  docker save "ainew-frontend:${VERSION}" "ainew-frontend:latest" | gzip > "${IMAGES_DIR}/ainew-frontend.tar.gz"
  docker save "dropt-api:local" | gzip > "${IMAGES_DIR}/dropt-api.tar.gz"
  repack_and_save "timescale/timescaledb:2.17.2-pg15" "${IMAGES_DIR}/timescaledb.tar.gz"
  repack_and_save "redis:7-alpine" "${IMAGES_DIR}/redis.tar.gz"
  repack_and_save "postgres:16-alpine" "${IMAGES_DIR}/postgres16.tar.gz"
  repack_and_save "prom/prometheus:v2.55.1" "${IMAGES_DIR}/prometheus.tar.gz"
  repack_and_save "prom/pushgateway:v1.11.0" "${IMAGES_DIR}/pushgateway.tar.gz"

  if [[ "$WITH_OLLAMA" -eq 1 ]]; then
    if [[ "$BUNDLE_OLLAMA" -eq 1 ]]; then
      echo "▶ Ollama imajı paketleniyor (--bundle-ollama, tam offline)..."
      if ! docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
        echo "  ollama/ollama:latest yok — çekiliyor..."
        docker pull --platform "$PLATFORM" ollama/ollama:latest || docker pull ollama/ollama:latest
      fi
      repack_and_save "ollama/ollama:latest" "${IMAGES_DIR}/ollama.tar.gz"

      echo "▶ Embedding modeli dışa aktarılıyor: ${EMBED_MODEL}"
      chmod +x scripts/export-ollama-embed-model.sh
      scripts/export-ollama-embed-model.sh \
        "${IMAGES_DIR}/ollama-models-${EMBED_MODEL}.tar.gz" \
        "" \
        "$EMBED_MODEL"
    else
      echo "▶ Ollama runtime paketin içine gömülmüyor — kurulumda '${OLLAMA_RUNTIME_RELEASE}'"
      echo "  release'inden bir kereye mahsus indirilip önbelleğe alınacak."
    fi

    # Kurulum betiğinin ollama'yı otomatik açması / runtime'ı indirmesi için işaret
    cat > "${STAGE}/WITH_OLLAMA" <<EOF
1
EMBED_MODEL=${EMBED_MODEL}
OLLAMA_IMAGE=ollama/ollama:latest
OLLAMA_RUNTIME_RELEASE=${OLLAMA_RUNTIME_RELEASE}
OLLAMA_RUNTIME_BASE_URL=${OLLAMA_RUNTIME_BASE_URL}
EOF
    cat >> "$STAGE/.env.example" <<EOF

# with-ollama paketi — RAG embedding için Ollama + ${EMBED_MODEL} dahildir
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_EMBED_MODEL=${EMBED_MODEL}
EOF
  fi

  # install-rhel.sh VERSION kanonik kullanır; .env.example'da tek satır yeterli (çift ekleme yok).
  _set_ex() {
    local key="$1" value="$2" f="$STAGE/.env.example"
    if grep -q "^${key}=" "$f" 2>/dev/null; then
      # İlk satırı güncelle, aynı key tekrarlarını sil
      awk -v k="$key" -v v="$value" '
        index($0, k "=") == 1 { if (!seen++) print k "=" v; next }
        { print }
      ' "$f" > "${f}.tmp" && mv "${f}.tmp" "$f"
    else
      echo "${key}=${value}" >> "$f"
    fi
  }
  _set_ex "BACKEND_IMAGE" "ainew-backend:${VERSION}"
  _set_ex "FRONTEND_IMAGE" "ainew-frontend:${VERSION}"
  _set_ex "DROPT_API_IMAGE" "dropt-api:local"
  _set_ex "DROPT_PULL_POLICY" "never"

  # GitHub'ın LFS'siz push'larda uyguladığı 100MB/dosya sert sınırı nedeniyle,
  # bu paket git'e commit edilecekse (ör. tamamen air-gapped hedeflere "git clone /
  # Download ZIP" ile taşınacaksa) 90MB'ı aşan imaj arşivleri parçalara bölünür.
  # install-rhel.sh, kurulumdan önce bu parçaları otomatik olarak geri birleştirir
  # (bkz. "Parçalanmış imaj arşivleri birleştiriliyor" adımı). scp/USB ile doğrudan
  # taşıyanlar için bu bölme gereksizdir ama zararsızdır (install-rhel.sh her durumda
  # doğru çalışır).
  # NOT: ollama-models-*.tar.gz docker load edilmez — parçalama yine de zararsız.
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

  echo "▶ Paket imaj envanteri kontrol ediliyor..."
  local_missing=0
  for need in \
      ainew-backend.tar.gz \
      ainew-frontend.tar.gz \
      dropt-api.tar.gz \
      timescaledb.tar.gz \
      redis.tar.gz \
      postgres16.tar.gz \
      prometheus.tar.gz \
      pushgateway.tar.gz; do
    if [[ -e "${IMAGES_DIR}/${need}" ]] || compgen -G "${IMAGES_DIR}/${need}.part*" > /dev/null 2>&1; then
      echo "  ✓ ${need}"
    else
      echo "  ✗ EKSİK: ${need}"
      local_missing=1
    fi
  done
  if [[ "$BUNDLE_OLLAMA" -eq 1 ]]; then
    if [[ -e "${IMAGES_DIR}/ollama.tar.gz" ]] || compgen -G "${IMAGES_DIR}/ollama.tar.gz.part*" > /dev/null 2>&1; then
      echo "  ✓ ollama.tar.gz"
    else
      echo "  ✗ EKSİK: ollama.tar.gz (--bundle-ollama)"
      local_missing=1
    fi
  fi
  if [[ "$local_missing" -ne 0 ]]; then
    echo "✖ Zorunlu imaj arşivleri eksik — paket üretilmeyecek."
    exit 1
  fi
else
  echo "▶ --no-images verildi, imaj derleme/kaydetme atlandı (kaynak koddan derlenecek)."
fi

# Pakette geliştirme compose kalıntısı / yanlış ad olmasın
if ! grep -q 'pull_policy: never' "$STAGE/docker-compose.yml" 2>/dev/null; then
  echo "✖ Paket docker-compose.yml offline stack değil (pull_policy: never yok)."
  exit 1
fi
if grep -qE '^\s*build:' "$STAGE/docker-compose.yml" 2>/dev/null; then
  echo "✖ Paket docker-compose.yml içinde build: var — offline paket için yasak."
  exit 1
fi
if ! grep -q 'docker-compose.dropt.yml' "$STAGE/docker-compose.yml" 2>/dev/null; then
  echo "✖ Paket docker-compose.yml Dropt include etmiyor."
  exit 1
fi

# ── 4. Arşivle ───────────────────────────────────────────────────────────────
echo "▶ Arşivleniyor (owner/group 0 — müşteride datatem UID görünmesin)..."
chown -R root:root "$STAGE" 2>/dev/null || true
tar -C dist --owner=0 --group=0 --numeric-owner -czf "${STAGE}.tar.gz" "$(basename "$STAGE")"
sha256sum "${STAGE}.tar.gz" > "${STAGE}.tar.gz.sha256"
du -sh "${STAGE}.tar.gz"

echo
echo "✔ Paket hazır: ${STAGE}.tar.gz"
echo "  İlk kurulum:"
echo "    tar xzf $(basename "${STAGE}.tar.gz") && cd $(basename "$STAGE") && sudo ./install-rhel.sh"
echo "  Compose dosyası: docker-compose.yml  (docker compose up -d --no-build)"
echo "  Güncelleme:"
echo "    tar xzf $(basename "${STAGE}.tar.gz") && cd $(basename "$STAGE")"
echo "    sudo ./update-rhel.sh --install-dir /data"
echo "  Geri alma:"
echo "    cd /data && sudo ./rollback-rhel.sh"
