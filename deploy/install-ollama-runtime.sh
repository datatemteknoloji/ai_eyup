#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Ollama Runtime — Tek Adım Kurulum (air-gapped / internetsiz sunucular için)
#
# install-rhel.sh / update-rhel.sh, "with-ollama" paketiyle kurulduğunda
# Ollama imajını + embedding modelini internetten OTOMATİK indirir. Sunucunun
# internet erişimi yoksa (veya indirme disk/ağ hatasıyla başarısız olduysa)
# bu adım atlanır ve Ollama profili devre dışı kalır.
#
# Bu betik, ollama-runtime-v1 GitHub release'inden BAŞKA (internet erişimi
# olan) bir makinede indirdiğiniz dosyaları alıp TEK KOMUTLA kurar: parçaları
# birleştirir, bütünlük doğrular (varsa), imajı docker/podman'a yükler,
# embedding modelini açar, .env'i günceller, servisleri Ollama profiliyle
# yeniden başlatır ve sağlık kontrolü yapar.
#
# Kullanım:
#   1) İnternet erişimi olan bir makinede indirin:
#        gh release download ollama-runtime-v1 --repo datatemteknoloji/ai_eyup
#      (veya https://github.com/datatemteknoloji/ai_eyup/releases/tag/ollama-runtime-v1
#       adresinden tarayıcıyla)
#   2) İndirilen dosyaları (ollama.tar.gz / ollama.tar.gz.part01, part02, ... /
#      ollama-models-nomic-embed-text.tar.gz / varsa .sha256 dosyaları) hedef
#      sunucuya taşıyın (scp, USB).
#   3) Kurulum dizinindeki bu betiği çalıştırın:
#        sudo ./install-ollama-runtime.sh --from /path/to/indirilen-dosyalar
#      (--from verilmezse betiğin kendi bulunduğu dizine bakar; dosyaları
#       doğrudan paket köküne kopyalayıp betiği oradan da çalıştırabilirsiniz)
#
# Argümanlar:
#   --from <dizin>          İndirilen dosyaların bulunduğu klasör (varsayılan: betiğin dizini)
#   --install-dir <dizin>   Kurulum dizini, .env burada aranır (varsayılan: /data)
#   --embed-model <isim>    Embedding model adı (varsayılan: .env'deki OLLAMA_EMBED_MODEL,
#                            yoksa nomic-embed-text)
#
# İdempotenttir: imaj zaten Docker/Podman'da veya model zaten diskteyse o
# adımı atlar; birden fazla kez güvenle çalıştırılabilir.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

c_green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red() { printf '\033[0;31m%s\033[0m\n' "$1"; }
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FROM_DIR="$SCRIPT_DIR"
INSTALL_DIR="/data"
EMBED_MODEL_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM_DIR="$(realpath -m "$2")"; shift 2 ;;
    --install-dir) INSTALL_DIR="$(realpath -m "$2")"; shift 2 ;;
    --embed-model) EMBED_MODEL_ARG="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,32p' "$0"
      exit 0
      ;;
    *) c_red "Bilinmeyen argüman: $1 (bkz. --help)"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  c_red "Bu betik root olarak çalıştırılmalı: sudo ./install-ollama-runtime.sh"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  c_red "docker komutu bulunamadı. Önce ./install-rhel.sh ile ana kurulumu yapın."
  exit 1
fi

ENV_FILE="$INSTALL_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  c_red "Kurulum bulunamadı: $ENV_FILE"
  c_yellow "Önce ana kurulumu yapın (sudo ./install-rhel.sh) ya da doğru dizini --install-dir ile verin."
  exit 1
fi

COMPOSE_FILE="$INSTALL_DIR/docker-compose.prod.yml"
[[ -f "$COMPOSE_FILE" ]] || COMPOSE_FILE="docker-compose.prod.yml"

DATA_DIR="$(grep '^DATA_DIR=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
[[ -z "$DATA_DIR" ]] && DATA_DIR="$INSTALL_DIR/data"
CACHE_DIR="$DATA_DIR/.ollama-runtime-cache"
mkdir -p "$CACHE_DIR"

echo
c_green "════════════════════════════════════════════════════════════════"
c_green " Ollama Runtime Kurulumu (tek adım)"
c_green "════════════════════════════════════════════════════════════════"
echo " Kaynak dosyalar : $FROM_DIR"
echo " Kurulum dizini  : $INSTALL_DIR"
echo " Veri dizini     : $DATA_DIR"
echo " Cache dizini    : $CACHE_DIR"
echo

# ── 1. Disk kontrolü (erken uyarı — "no space left on device" bilindik hata) ─
step "Disk alanı kontrol ediliyor"
df -h "$CACHE_DIR" "$INSTALL_DIR" 2>/dev/null | tail -n +1 || true
AVAIL_KB="$(df -Pk "$CACHE_DIR" | awk 'NR==2 {print $4}')"
if [[ -n "${AVAIL_KB:-}" && "$AVAIL_KB" -lt 8388608 ]]; then
  c_yellow "⚠ ${CACHE_DIR} bölümünde 8GB'dan az boş alan var (Ollama imajı ~3-4GB). Yetersiz kalabilir."
fi

# ── 2. Ollama imajı ──────────────────────────────────────────────────────
step "Ollama imajı kontrol ediliyor"
if docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
  c_green "✓ ollama/ollama:latest zaten yüklü — indirme/yükleme atlandı."
else
  IMG_TAR=""
  if [[ -s "$FROM_DIR/ollama.tar.gz" ]]; then
    IMG_TAR="$FROM_DIR/ollama.tar.gz"
  elif compgen -G "$FROM_DIR/ollama.tar.gz.part*" > /dev/null 2>&1; then
    step "Parçalar birleştiriliyor (ollama.tar.gz.part*)"
    if [[ -s "$FROM_DIR/ollama.tar.gz.parts.sha256" ]]; then
      (cd "$FROM_DIR" && sha256sum -c ollama.tar.gz.parts.sha256) || {
        c_red "Parça bütünlük doğrulaması başarısız — dosyalar bozuk/eksik olabilir."; exit 1; }
      c_green "✓ Parça bütünlüğü doğrulandı."
    fi
    cat "$FROM_DIR"/ollama.tar.gz.part* > "$CACHE_DIR/ollama.tar.gz"
    IMG_TAR="$CACHE_DIR/ollama.tar.gz"
    c_green "✓ Parçalar birleştirildi: $IMG_TAR"
  else
    c_red "ollama.tar.gz (veya .part parçaları) bulunamadı: $FROM_DIR"
    c_yellow "İndirme: gh release download ollama-runtime-v1 --repo datatemteknoloji/ai_eyup"
    c_yellow "Ayrıntı: docs/INSTALL_RHEL.md §5.3"
    exit 1
  fi

  if [[ -s "${IMG_TAR}.sha256" ]]; then
    (cd "$(dirname "$IMG_TAR")" && sha256sum -c "$(basename "$IMG_TAR").sha256") || {
      c_red "Bütünlük doğrulaması başarısız: $IMG_TAR"; exit 1; }
    c_green "✓ Bütünlük doğrulandı: $(basename "$IMG_TAR")"
  fi

  step "Ollama imajı yükleniyor (docker/podman load)"
  gunzip -c "$IMG_TAR" | docker load
  if docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
    c_green "✓ ollama/ollama:latest yüklendi."
  else
    c_red "docker load tamamlandı ama 'ollama/ollama:latest' bulunamadı — yukarıdaki çıktıyı kontrol edin."
    exit 1
  fi
  # Bir sonraki kurulum/güncellemenin ağa çıkmaması için kalıcı önbelleğe koy.
  if [[ "$IMG_TAR" != "$CACHE_DIR/ollama.tar.gz" ]]; then
    cp -f "$IMG_TAR" "$CACHE_DIR/ollama.tar.gz" 2>/dev/null || true
  fi
fi

# ── 3. Model(ler) ─────────────────────────────────────────────────────────
# $FROM_DIR içindeki TÜM ollama-models-*.tar.gz[.part*] paketlerini açar —
# yalnızca embedding modeliyle sınırlı değildir. Ör. ollama-gpt-oss-20b-v1
# release'inden indirilen dosyalar (ollama-models-gpt-oss-20b.tar.gz.part01..07
# + ollama-models-nomic-embed-text.tar.gz) aynı klasöre konursa ikisi de açılır.
# Büyük/ek bir chat modelini SONRADAN, tekil olarak eklemek için (bu betiği
# tekrar çalıştırmadan) deploy/install-ollama-model.sh --model <isim> tercih edin.
EMBED_MODEL="${EMBED_MODEL_ARG:-}"
[[ -z "$EMBED_MODEL" ]] && EMBED_MODEL="$(grep '^OLLAMA_EMBED_MODEL=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"

step "Model paketleri kontrol ediliyor (embedding: $EMBED_MODEL)"
if [[ -d "$DATA_DIR/ollama/models" ]] && find "$DATA_DIR/ollama/models" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
  c_green "✓ Model(ler) zaten diskte — açma işlemi atlandı (ek model eklemek için deploy/install-ollama-model.sh kullanın)."
else
  INSTALLED_ANY=0

  # Parçalanmamış tam dosyalar
  for FULL in "$FROM_DIR"/ollama-models-*.tar.gz; do
    [[ -s "$FULL" ]] || continue
    BASE="$(basename "$FULL")"
    if [[ -s "${FULL}.sha256" ]]; then
      (cd "$FROM_DIR" && sha256sum -c "${BASE}.sha256") || {
        c_red "Bütünlük doğrulaması başarısız: ${BASE} — atlanıyor."; continue; }
      c_green "✓ Bütünlük doğrulandı: ${BASE}"
    fi
    mkdir -p "$DATA_DIR/ollama"
    tar xzf "$FULL" -C "$DATA_DIR/ollama"
    [[ "$FROM_DIR" != "$CACHE_DIR" ]] && cp -f "$FULL" "$CACHE_DIR/" 2>/dev/null || true
    c_green "✓ Model açıldı: ${BASE}"
    INSTALLED_ANY=1
  done

  # Parçalanmış dosyalar: ollama-models-<isim>.tar.gz.part01, part02, ...
  for PART1 in "$FROM_DIR"/ollama-models-*.tar.gz.part01; do
    [[ -s "$PART1" ]] || continue
    BASE="$(basename "${PART1%.part01}")"
    if [[ -s "$FROM_DIR/${BASE}.parts.sha256" ]]; then
      (cd "$FROM_DIR" && sha256sum -c "${BASE}.parts.sha256") || {
        c_red "Parça bütünlük doğrulaması başarısız: ${BASE} — atlanıyor."; continue; }
      c_green "✓ Parça bütünlüğü doğrulandı: ${BASE}"
    fi
    mkdir -p "$CACHE_DIR" "$DATA_DIR/ollama"
    cat "$FROM_DIR/${BASE}".part* > "$CACHE_DIR/${BASE}"
    tar xzf "$CACHE_DIR/${BASE}" -C "$DATA_DIR/ollama"
    c_green "✓ Model açıldı (parçalardan birleştirildi): ${BASE}"
    INSTALLED_ANY=1
  done

  if [[ "$INSTALLED_ANY" -eq 0 ]]; then
    c_red "ollama-models-*.tar.gz (veya .part parçaları) bulunamadı: $FROM_DIR"
    exit 1
  fi
  chmod -R 777 "$DATA_DIR/ollama" 2>/dev/null || true
  c_green "✓ Model paketleri açıldı: $DATA_DIR/ollama"
fi

# ── 4. .env güncelle ──────────────────────────────────────────────────────
set_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}
set_env "OLLAMA_URL" "http://127.0.0.1:11434"
set_env "OLLAMA_EMBED_MODEL" "$EMBED_MODEL"

# ── 5. Servisleri Ollama profiliyle (yeniden) başlat ─────────────────────
step "Servisler Ollama profiliyle başlatılıyor"
cd "$INSTALL_DIR"
if docker compose -f "$COMPOSE_FILE" up -d --help 2>&1 | grep -q -- '--pull'; then
  docker compose --profile ollama -f "$COMPOSE_FILE" up -d --no-build --pull never
else
  docker compose --profile ollama -f "$COMPOSE_FILE" up -d --no-build
fi

# ── 6. Sağlık kontrolü ────────────────────────────────────────────────────
step "Ollama sağlık kontrolü"
OLLAMA_OK=0
for i in $(seq 1 45); do
  if curl -sf --max-time 3 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    OLLAMA_OK=1
    break
  fi
  sleep 2
done

echo
if [[ "$OLLAMA_OK" -eq 1 ]]; then
  c_green "✔ Ollama hazır: http://127.0.0.1:11434"
  if docker exec server_management_ollama ollama list 2>/dev/null | grep -qi "${EMBED_MODEL%%:*}"; then
    c_green "✔ Embedding modeli listede: $EMBED_MODEL"
  else
    c_yellow "⚠ $EMBED_MODEL 'ollama list' çıktısında görünmüyor:"
    c_yellow "  docker exec server_management_ollama ollama list"
  fi
  c_green "════════════════════════════════════════════════════════════════"
  c_green " Ollama runtime kurulumu tamamlandı."
  c_green "════════════════════════════════════════════════════════════════"
  echo " Ek bir chat modeli (ör. llama3.2:3b) eklemek için:"
  echo "   docker compose -f $COMPOSE_FILE exec ollama ollama pull llama3.2:3b"
else
  c_red "⚠ Ollama 90 saniye içinde yanıt vermedi."
  c_yellow "  Log: cd $INSTALL_DIR && docker compose -f $COMPOSE_FILE --profile ollama logs -f ollama"
  exit 1
fi
