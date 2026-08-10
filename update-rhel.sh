#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# RHEL 9 güncelleme betiği — Altyapı Yönetim Platformu
#
# Yeni sürüm paketini mevcut kuruluma uygular. Kalıcı veri (DATA_DIR) dokunulmaz.
# Güncellemeden ÖNCE otomatik yedek alınır; sorun olursa rollback-rhel.sh ile
# önceki sürüme dönülebilir.
#
# Kullanım (yeni paket dizininden):
#   tar xzf ainew-1.0.1-linux-amd64.tar.gz
#   cd ainew-1.0.1-linux-amd64
#   sudo ./update-rhel.sh --install-dir /data
#   sudo ./update-rhel.sh --install-dir /data --ollama-files /root/ollama-runtime
#     (with-ollama paketinde, internet erişimi olmayan sunucularda: elle
#      indirilen ollama.tar.gz[.part*] + ollama-models-*.tar.gz dosyalarının
#      bulunduğu klasörü işaret eder — internete hiç çıkılmadan yüklenir)
#
# Ortam değişkenleri:
#   INSTALL_DIR   Hedef kurulum (varsayılan: --install-dir veya /data)
#   SKIP_DB_BACKUP=1  Postgres dump atlanır (hızlı ama rollback'te DB geri alınamaz)
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

NEW_PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE=".env"
DEFAULT_INSTALL_DIR="/data"
COMPOSE_FILE="docker-compose.yml"

# Müşteri paketinde offline stack adı docker-compose.yml'dir (Dropt include).
# Eski kurulumlarda kalan docker-compose.prod.yml Dropt'suz / eski olabilir —
# include içeren yml tercih edilir; prod varsa yml ile senkronlanır.
resolve_compose_file() {
  local dir="$1"
  local yml="$dir/docker-compose.yml"
  local prod="$dir/docker-compose.prod.yml"
  if [[ -f "$yml" ]] && grep -q 'docker-compose.dropt.yml' "$yml" 2>/dev/null; then
    if [[ -f "$prod" ]] && ! grep -q 'docker-compose.dropt.yml' "$prod" 2>/dev/null; then
      cp -a "$yml" "$prod"
      c_yellow "Eski docker-compose.prod.yml Dropt include'suzdu — docker-compose.yml ile güncellendi."
    elif [[ -f "$prod" ]]; then
      # İkisi de Dropt'lu: yml kanonik; prod'u hizala (karışıklığı önle)
      cp -a "$yml" "$prod"
    fi
    printf '%s' "docker-compose.yml"
    return 0
  fi
  if [[ -f "$prod" ]] && grep -q 'docker-compose.dropt.yml' "$prod" 2>/dev/null; then
    printf '%s' "docker-compose.prod.yml"
    return 0
  fi
  if [[ -f "$yml" ]]; then
    printf '%s' "docker-compose.yml"
    return 0
  fi
  if [[ -f "$prod" ]]; then
    printf '%s' "docker-compose.prod.yml"
    return 0
  fi
  printf '%s' "docker-compose.yml"
}

c_green()  { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red()    { printf '\033[0;31m%s\033[0m\n' "$1"; }
step()     { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

# Ollama imajı + embedding modeli, uygulama sürümünden bağımsız sabit bir
# GitHub release'te barınır (nadiren değişirler). Paket içine gömülü değillerse
# (lean --with-ollama), burada BİR KEREYE MAHSUS indirilip $DATA_DIR altına
# önbelleklenir — imaj zaten Docker'da / model zaten diskteyse ağ hiç kullanılmaz.
_download_ollama_runtime_asset() {
  local name="$1" cache_dir="$2" base_url="$3"
  local out="${cache_dir}/${name}"
  [[ -s "$out" ]] && return 0
  if ! command -v curl >/dev/null 2>&1; then
    c_red "curl bulunamadı — Ollama runtime indirilemiyor."
    c_yellow "Manuel: ${base_url}/${name} dosyasını indirip ${cache_dir}/ altına koyup tekrar deneyin."
    return 1
  fi
  local parts_sha="${cache_dir}/${name}.parts.sha256"
  if curl -fsSL --retry 3 "${base_url}/${name}.parts.sha256" -o "$parts_sha" 2>/dev/null; then
    c_yellow "İndiriliyor (parçalı): ${name} ..."
    local partname
    while read -r _ partname; do
      [[ -z "$partname" ]] && continue
      [[ -s "${cache_dir}/${partname}" ]] && continue
      curl -fL --retry 3 --progress-bar "${base_url}/${partname}" -o "${cache_dir}/${partname}" || {
        c_red "İndirme başarısız: ${partname}"; return 1; }
    done < "$parts_sha"
    (cd "$cache_dir" && sha256sum -c "$(basename "$parts_sha")") || {
      c_red "Parça bütünlük doğrulaması başarısız: ${name}"; return 1; }
    rm -f "$parts_sha"
    # NOT: glob önce ".parts.sha256" silinmeden çalıştırılırsa "part*" deseni
    # o dosyayı da (part+s...) yanlışlıkla eşleştirir — üstteki rm bu yüzden önce.
    cat "${cache_dir}/${name}".part* > "$out"
    rm -f "${cache_dir}/${name}".part*
  else
    c_yellow "İndiriliyor: ${name} ..."
    curl -fL --retry 3 --progress-bar "${base_url}/${name}" -o "$out" || {
      c_red "İndirme başarısız: ${name}"; return 1; }
  fi
  local sha_file="${cache_dir}/${name}.sha256"
  if curl -fsSL --retry 3 "${base_url}/${name}.sha256" -o "$sha_file" 2>/dev/null; then
    (cd "$cache_dir" && sha256sum -c "$(basename "$sha_file")") || {
      c_red "Bütünlük doğrulaması başarısız: ${name}"; rm -f "$out"; return 1; }
  fi
}

# --ollama-files ile verilen klasörden (elle indirilmiş ollama.tar.gz veya
# .part parçaları) imajı docker/podman'a yükler — ağa hiç çıkmaz.
_load_ollama_image_from_dir() {
  local src_dir="$1" cache_dir="$2"
  local img_tar=""
  if [[ -s "${src_dir}/ollama.tar.gz" ]]; then
    img_tar="${src_dir}/ollama.tar.gz"
  elif compgen -G "${src_dir}/ollama.tar.gz.part*" > /dev/null 2>&1; then
    if [[ -s "${src_dir}/ollama.tar.gz.parts.sha256" ]]; then
      (cd "$src_dir" && sha256sum -c ollama.tar.gz.parts.sha256) || {
        c_red "Parça bütünlük doğrulaması başarısız: ${src_dir}/ollama.tar.gz.part*"; return 1; }
      c_green "✓ Parça bütünlüğü doğrulandı."
    fi
    mkdir -p "$cache_dir"
    cat "${src_dir}"/ollama.tar.gz.part* > "${cache_dir}/ollama.tar.gz"
    img_tar="${cache_dir}/ollama.tar.gz"
  else
    c_red "ollama.tar.gz (veya .part parçaları) bulunamadı: ${src_dir}"
    return 1
  fi
  if [[ -s "${img_tar}.sha256" ]]; then
    (cd "$(dirname "$img_tar")" && sha256sum -c "$(basename "$img_tar").sha256") || {
      c_red "Bütünlük doğrulaması başarısız: ${img_tar}"; return 1; }
    c_green "✓ Bütünlük doğrulandı: $(basename "$img_tar")"
  fi
  c_yellow "Yükleniyor: $(basename "$img_tar")"
  gunzip -c "$img_tar" | docker load
  if [[ "$img_tar" != "${cache_dir}/ollama.tar.gz" ]]; then
    mkdir -p "$cache_dir"
    cp -f "$img_tar" "${cache_dir}/ollama.tar.gz" 2>/dev/null || true
  fi
}

# --ollama-files ile verilen klasörden embedding modelini açar — ağa hiç çıkmaz.
_load_ollama_model_from_dir() {
  local src_dir="$1" cache_dir="$2" embed_model="$3" data_dir="$4"
  local model_tar=""
  local cand
  for cand in "${src_dir}/ollama-models-${embed_model}.tar.gz" "${src_dir}"/ollama-models-*.tar.gz; do
    [[ -s "$cand" ]] && { model_tar="$cand"; break; }
  done
  if [[ -z "$model_tar" ]]; then
    c_red "ollama-models-*.tar.gz bulunamadı: ${src_dir}"
    return 1
  fi
  if [[ -s "${model_tar}.sha256" ]]; then
    (cd "$(dirname "$model_tar")" && sha256sum -c "$(basename "$model_tar").sha256") || {
      c_red "Bütünlük doğrulaması başarısız: ${model_tar}"; return 1; }
    c_green "✓ Bütünlük doğrulandı: $(basename "$model_tar")"
  fi
  mkdir -p "$data_dir/ollama"
  tar xzf "$model_tar" -C "$data_dir/ollama"
  chmod -R 777 "$data_dir/ollama" 2>/dev/null || true
  if [[ "$(dirname "$model_tar")" != "$cache_dir" ]]; then
    mkdir -p "$cache_dir"
    cp -f "$model_tar" "${cache_dir}/" 2>/dev/null || true
  fi
}

ensure_ollama_runtime() {
  local marker="$INSTALL_DIR/WITH_OLLAMA"
  [[ -f "$marker" ]] || return 0
  local release_base embed_model cache_dir
  release_base="$(grep '^OLLAMA_RUNTIME_BASE_URL=' "$marker" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  embed_model="$(grep '^EMBED_MODEL=' "$marker" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  embed_model="${embed_model:-nomic-embed-text}"
  cache_dir="$DATA_DIR/.ollama-runtime-cache"

  if docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
    c_green "  ✓ ollama/ollama:latest zaten yüklü — indirme atlandı."
  elif compgen -G "${IMAGES_DIR}/ollama.tar.gz*" > /dev/null 2>&1; then
    c_yellow "  · ollama/ollama:latest paket içinde gömülü (yukarıda yüklendi)."
  elif [[ -n "$OLLAMA_FILES_DIR" ]]; then
    step "Ollama imajı --ollama-files klasöründen yükleniyor: $OLLAMA_FILES_DIR"
    mkdir -p "$cache_dir"
    if _load_ollama_image_from_dir "$OLLAMA_FILES_DIR" "$cache_dir"; then
      c_green "✓ ollama/ollama:latest yüklendi (--ollama-files, ağa çıkılmadı)."
    else
      c_red "Ollama imajı --ollama-files klasöründen yüklenemedi — with-ollama profili devre dışı kalabilir."
    fi
  elif [[ -z "$release_base" ]]; then
    c_yellow "  · WITH_OLLAMA runtime release bilgisi yok, ollama imajı atlanıyor."
  else
    mkdir -p "$cache_dir"
    step "Ollama imajı indiriliyor (bir kereye mahsus)"
    if _download_ollama_runtime_asset "ollama.tar.gz" "$cache_dir" "$release_base"; then
      c_yellow "Yükleniyor: ollama.tar.gz"
      gunzip -c "$cache_dir/ollama.tar.gz" | docker load
      c_green "✓ ollama/ollama:latest yüklendi ve önbelleklendi: $cache_dir"
    else
      c_red "Ollama runtime imajı indirilemedi — with-ollama profili devre dışı kalabilir."
      c_yellow "  İnternetsiz kurulum için: sudo ./update-rhel.sh --install-dir $INSTALL_DIR --ollama-files <dizin>"
    fi
  fi

  if [[ -d "$DATA_DIR/ollama/models" ]] && find "$DATA_DIR/ollama/models" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
    c_green "  ✓ Embedding modeli ($embed_model) zaten diskte — indirme atlandı."
  elif compgen -G "${IMAGES_DIR}/ollama-models-*.tar.gz*" > /dev/null 2>&1; then
    : # paket içinde gömülü — mevcut akış bunu işleyecek
  elif [[ -n "$OLLAMA_FILES_DIR" ]]; then
    step "Embedding modeli --ollama-files klasöründen açılıyor: $OLLAMA_FILES_DIR"
    mkdir -p "$cache_dir"
    if _load_ollama_model_from_dir "$OLLAMA_FILES_DIR" "$cache_dir" "$embed_model" "$DATA_DIR"; then
      c_green "✓ Embedding modeli açıldı (--ollama-files, ağa çıkılmadı)."
    else
      c_red "Embedding modeli --ollama-files klasöründen açılamadı — RAG embedding çalışmayabilir."
    fi
  elif [[ -z "$release_base" ]]; then
    c_yellow "  · WITH_OLLAMA runtime release bilgisi yok, embedding modeli atlanıyor."
  else
    mkdir -p "$cache_dir" "$DATA_DIR/ollama"
    step "Embedding modeli indiriliyor (bir kereye mahsus): ${embed_model}"
    if _download_ollama_runtime_asset "ollama-models-${embed_model}.tar.gz" "$cache_dir" "$release_base"; then
      tar xzf "$cache_dir/ollama-models-${embed_model}.tar.gz" -C "$DATA_DIR/ollama"
      chmod -R 777 "$DATA_DIR/ollama" 2>/dev/null || true
      c_green "✓ Embedding modeli açıldı ve önbelleklendi: $cache_dir"
    else
      c_red "Embedding modeli indirilemedi — RAG embedding çalışmayabilir."
      c_yellow "  İnternetsiz kurulum için: sudo ./update-rhel.sh --install-dir $INSTALL_DIR --ollama-files <dizin>"
    fi
  fi
}

INSTALL_DIR="${INSTALL_DIR:-}"
SKIP_DB_BACKUP="${SKIP_DB_BACKUP:-0}"
OLLAMA_FILES_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --skip-db-backup) SKIP_DB_BACKUP=1; shift ;;
    --ollama-files) OLLAMA_FILES_DIR="$(realpath -m "$2")"; shift 2 ;;
    -h|--help)
      sed -n '2,21p' "$0"
      exit 0
      ;;
    *) c_red "Bilinmeyen argüman: $1"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  c_red "Bu betik root olarak çalıştırılmalı: sudo ./update-rhel.sh"
  exit 1
fi

if [[ -z "$INSTALL_DIR" ]]; then
  if [[ -t 0 ]]; then
    read -rp "Mevcut kurulum dizini [${DEFAULT_INSTALL_DIR}]: " INSTALL_DIR
    INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
  else
    INSTALL_DIR="$DEFAULT_INSTALL_DIR"
  fi
fi
INSTALL_DIR="$(realpath -m "$INSTALL_DIR")"

if [[ ! -f "$INSTALL_DIR/$ENV_FILE" ]]; then
  c_red "Kurulum bulunamadı: $INSTALL_DIR/$ENV_FILE"
  c_yellow "İlk kurulum için: sudo ./install-rhel.sh"
  exit 1
fi

if [[ "$NEW_PKG_DIR" == "$INSTALL_DIR" ]]; then
  c_red "update-rhel.sh yeni paket dizininden çalıştırılmalı, kurulum dizininin içinden değil."
  c_yellow "Örnek: cd /root/ainew-1.0.1-linux-amd64 && sudo ./update-rhel.sh --install-dir $INSTALL_DIR"
  exit 1
fi

DATA_DIR="$(grep '^DATA_DIR=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2-)"
[[ -z "$DATA_DIR" ]] && DATA_DIR="$INSTALL_DIR/data"

OLD_VERSION="$(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo "unknown")"
NEW_VERSION="$(cat "$NEW_PKG_DIR/VERSION" 2>/dev/null || echo "unknown")"
OLD_BACKEND="$(grep '^BACKEND_IMAGE=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2- || true)"
OLD_FRONTEND="$(grep '^FRONTEND_IMAGE=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2- || true)"
# VERSION dosyası kanonik — .env.example eski etiket taşıyabilir (1.0.9.21 vs 1.0.9.22).
NEW_BACKEND="ainew-backend:${NEW_VERSION}"
NEW_FRONTEND="ainew-frontend:${NEW_VERSION}"
# Dump için mevcut kurulum compose'u (henüz paket kopyalanmadı)
COMPOSE_FILE="$(resolve_compose_file "$INSTALL_DIR")"

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$DATA_DIR/backups/pre-update-${OLD_VERSION}-to-${NEW_VERSION}-${TS}"

echo
c_green "════════════════════════════════════════════════════════════════"
c_green " Güncelleme: ${OLD_VERSION} → ${NEW_VERSION}"
c_green "════════════════════════════════════════════════════════════════"
echo " Kurulum      : $INSTALL_DIR"
echo " Veri         : $DATA_DIR"
echo " Eski imajlar : ${OLD_BACKEND:-?} / ${OLD_FRONTEND:-?}"
echo " Yeni imajlar : $NEW_BACKEND / $NEW_FRONTEND"
echo " Yedek        : $BACKUP_DIR"
echo

# ── 1. Yedek ────────────────────────────────────────────────────────────────
step "Güncelleme öncesi yedek alınıyor"
mkdir -p "$BACKUP_DIR"
cp -a "$INSTALL_DIR/$ENV_FILE" "$BACKUP_DIR/env"
[[ -f "$INSTALL_DIR/VERSION" ]] && cp -a "$INSTALL_DIR/VERSION" "$BACKUP_DIR/VERSION" || true
cat > "$BACKUP_DIR/previous_images.txt" <<EOF
BACKEND_IMAGE=${OLD_BACKEND}
FRONTEND_IMAGE=${OLD_FRONTEND}
OLD_VERSION=${OLD_VERSION}
NEW_VERSION=${NEW_VERSION}
INSTALL_DIR=${INSTALL_DIR}
DATA_DIR=${DATA_DIR}
EOF

if [[ "$SKIP_DB_BACKUP" != "1" ]]; then
  c_yellow "Postgres dump alınıyor (birkaç dakika sürebilir)..."
  set -a; # shellcheck disable=SC1091
  source "$INSTALL_DIR/$ENV_FILE"
  set +a
  if docker compose -f "$INSTALL_DIR/$COMPOSE_FILE" --project-directory "$INSTALL_DIR" \
      exec -T db pg_dump -U postgres server_management > "$BACKUP_DIR/db.sql" 2>/dev/null; then
    c_green "DB yedeği: $BACKUP_DIR/db.sql ($(du -h "$BACKUP_DIR/db.sql" | awk '{print $1}'))"
  else
    c_yellow "DB dump alınamadı (db ayakta değil olabilir) — sadece imaj rollback mümkün olacak."
    rm -f "$BACKUP_DIR/db.sql"
  fi
else
  c_yellow "SKIP_DB_BACKUP=1 — Postgres dump atlandı."
fi
ln -sfn "$BACKUP_DIR" "$DATA_DIR/backups/latest"
c_green "Yedek tamam: $BACKUP_DIR"

# ── 2. Paket dosyalarını kurulum dizinine kopyala (veri/.env hariç) ─────────
step "Yeni paket dosyaları kuruluma kopyalanıyor"
# data/ ve .env asla üzerine yazılmaz — kalıcı yapılandırma ve DB korunur.
if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude '.env' \
    --exclude 'data/' \
    --exclude '.git/' \
    --exclude 'backups/' \
    "$NEW_PKG_DIR"/ "$INSTALL_DIR"/
else
  # rsync yoksa: .env'i geçici sakla, kopyala, geri koy
  cp -a "$INSTALL_DIR/$ENV_FILE" "/tmp/ainew-env-preserve-$$"
  cp -a "$NEW_PKG_DIR"/. "$INSTALL_DIR"/
  mv "/tmp/ainew-env-preserve-$$" "$INSTALL_DIR/$ENV_FILE"
fi
chmod +x "$INSTALL_DIR"/install-rhel.sh "$INSTALL_DIR"/update-rhel.sh "$INSTALL_DIR"/rollback-rhel.sh \
  "$INSTALL_DIR"/ainew-apply-update.sh 2>/dev/null || true
# GUI wrapper'ı DATA_DIR/updates/bin altına senkronla
mkdir -p "$DATA_DIR/updates"/{incoming,prepared,bin}
mkdir -p "$DATA_DIR/dropt"/{postgres,redis,ssh-keys,artifacts,keytabs,certs,rpms}
if [[ -f "$INSTALL_DIR/ainew-apply-update.sh" ]]; then
  cp -a "$INSTALL_DIR/ainew-apply-update.sh" "$DATA_DIR/updates/bin/ainew-apply-update.sh"
  chmod +x "$DATA_DIR/updates/bin/ainew-apply-update.sh" 2>/dev/null || true
fi
c_green "Paket dosyaları güncellendi ( .env ve data/ korundu )."
COMPOSE_FILE="$(resolve_compose_file "$INSTALL_DIR")"
c_green "Compose dosyası: $COMPOSE_FILE"

# TLS — eksikse host'ta üret (frontend entrypoint de üretir; host dosyası kalıcı olsun)
step "TLS sertifikası kontrol ediliyor"
mkdir -p "$DATA_DIR/certs"
_CERT="$DATA_DIR/certs/server.crt"
_KEY="$DATA_DIR/certs/server.key"
if [[ -f "$_CERT" && -f "$_KEY" ]]; then
  c_green "Mevcut sertifika: $_CERT"
else
  _CN="$(grep '^PRIMARY_IP=' "$INSTALL_DIR/$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  [[ -z "$_CN" ]] && _CN="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -z "$_CN" ]] && _CN="localhost"
  if command -v openssl >/dev/null 2>&1; then
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
      -keyout "$_KEY" -out "$_CERT" \
      -subj "/C=TR/O=ainew/CN=${_CN}" \
      -addext "subjectAltName=IP:${_CN},DNS:localhost" 2>/dev/null \
      || openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
           -keyout "$_KEY" -out "$_CERT" \
           -subj "/C=TR/O=ainew/CN=${_CN}"
    chmod 600 "$_KEY" 2>/dev/null || true
    chmod 644 "$_CERT" 2>/dev/null || true
    c_green "Self-signed sertifika üretildi: $_CERT"
  else
    c_yellow "openssl yok — frontend entrypoint ilk start'ta sertifika üretecek (certs mount yazılabilir olmalı)."
  fi
fi

# ── 3. İmaj etiketlerini .env'de güncelle ───────────────────────────────────
step ".env imaj etiketleri güncelleniyor"
set_env() {
  local key="$1" value="$2" file="$3"
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}
set_env "BACKEND_IMAGE"  "$NEW_BACKEND"  "$INSTALL_DIR/$ENV_FILE"
set_env "FRONTEND_IMAGE" "$NEW_FRONTEND" "$INSTALL_DIR/$ENV_FILE"
set_env "APP_VERSION"    "$NEW_VERSION"  "$INSTALL_DIR/$ENV_FILE"
# Level 1 / Dropt — eksik anahtarları tamamla (mevcut secret'ları bozma)
fill_if_empty() {
  local key="$1" value="$2" file="$3"
  _is_ph() {
    local v="${1:-}"
    [[ -z "$v" ]] && return 0
    local u
    u="$(printf '%s' "$v" | tr '[:lower:]' '[:upper:]')"
    [[ "$u" == CHANGE_ME* || "$u" == GENERATE_* || "$u" == REPLACE-* || "$u" == TODO* || "$u" == YOUR_* ]] && return 0
    return 1
  }
  if ! grep -q "^${key}=" "$file" 2>/dev/null; then
    echo "${key}=${value}" >> "$file"
  else
    local cur
    cur="$(grep "^${key}=" "$file" | head -1 | cut -d= -f2-)"
    if _is_ph "$cur"; then
      # Canlı volume'da sessizce değiştirmek veriyi kırar
      if [[ "$key" == "SECRET_KEY" ]]; then
        c_yellow " ⚠ SECRET_KEY hâlâ placeholder — DB re-encrypt: ./scripts/rotate-secrets.sh"
      elif [[ "$key" == "POSTGRES_PASSWORD" ]]; then
        c_yellow " ⚠ POSTGRES_PASSWORD hâlâ placeholder — güvenli rotate: ./scripts/rotate-secrets.sh --postgres"
      else
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
      fi
    fi
  fi
}
fill_if_empty "SECRET_KEY" "$(openssl rand -hex 32)" "$INSTALL_DIR/$ENV_FILE"
fill_if_empty "POSTGRES_PASSWORD" "$(openssl rand -hex 16)" "$INSTALL_DIR/$ENV_FILE"
fill_if_empty "AINEW_BRIDGE_SECRET" "$(openssl rand -hex 24)" "$INSTALL_DIR/$ENV_FILE"
fill_if_empty "DROPT_API_URL" "http://127.0.0.1:8001" "$INSTALL_DIR/$ENV_FILE"
fill_if_empty "DROPT_POSTGRES_USER" "dtt" "$INSTALL_DIR/$ENV_FILE"
fill_if_empty "DROPT_POSTGRES_PASSWORD" "$(openssl rand -hex 16)" "$INSTALL_DIR/$ENV_FILE"
fill_if_empty "DROPT_POSTGRES_DB" "dttportal" "$INSTALL_DIR/$ENV_FILE"
fill_if_empty "DROPT_API_IMAGE" "dropt-api:local" "$INSTALL_DIR/$ENV_FILE"
fill_if_empty "DROPT_PULL_POLICY" "never" "$INSTALL_DIR/$ENV_FILE"
fill_if_empty "DATA_DIR" "$DATA_DIR" "$INSTALL_DIR/$ENV_FILE"
if [[ -f "$INSTALL_DIR/dropt/.env.example" && ! -f "$INSTALL_DIR/dropt/.env" ]]; then
  cp "$INSTALL_DIR/dropt/.env.example" "$INSTALL_DIR/dropt/.env"
fi
# Dropt bağlantı bilgilerini ana .env ile hizala (placeholder DATABASE_URL kalmasın)
if [[ -f "$INSTALL_DIR/dropt/.env" ]]; then
  _DPG="$(grep '^DROPT_POSTGRES_PASSWORD=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2-)"
  _BR="$(grep '^AINEW_BRIDGE_SECRET=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2-)"
  _dropt_set_u() {
    local key="$1" value="$2" f="$INSTALL_DIR/dropt/.env"
    if grep -q "^${key}=" "$f" 2>/dev/null; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$f"
    else
      echo "${key}=${value}" >> "$f"
    fi
  }
  _dropt_set_u "POSTGRES_PASSWORD" "${_DPG}"
  _dropt_set_u "DATABASE_URL" "postgresql+psycopg://dtt:${_DPG}@dropt-db:5432/dttportal"
  _dropt_set_u "REDIS_URL" "redis://dropt-redis:6379/0"
  _dropt_set_u "AINEW_BRIDGE_SECRET" "${_BR}"
  _fk="$(grep '^FERNET_KEY=' "$INSTALL_DIR/dropt/.env" | head -1 | cut -d= -f2- || true)"
  if [[ -z "$_fk" || "$_fk" == replace-* || "$_fk" == change-me* ]]; then
    _nk="$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' 2>/dev/null || true)"
    [[ -n "$_nk" ]] && _dropt_set_u "FERNET_KEY" "$_nk"
  fi
fi
chmod 600 "$INSTALL_DIR/$ENV_FILE" "$INSTALL_DIR/dropt/.env" 2>/dev/null || true
c_green "BACKEND_IMAGE=$NEW_BACKEND"
c_green "FRONTEND_IMAGE=$NEW_FRONTEND"
c_green "APP_VERSION=$NEW_VERSION"

# ── 4. Yeni imajları yükle (install ile aynı: tüm images/*.tar.gz) ──────────
step "Yeni Docker imajları yükleniyor"
IMAGES_DIR="$INSTALL_DIR/images"
if compgen -G "${IMAGES_DIR}/*.tar.gz.part*" > /dev/null 2>&1; then
  c_yellow "Parçalanmış imaj arşivleri birleştiriliyor..."
  for part1 in "${IMAGES_DIR}"/*.tar.gz.part01; do
    [[ -e "$part1" ]] || continue
    target="${part1%.part01}"
    mapfile -t sorted < <(ls -1 "${target}".part* 2>/dev/null | sort -V)
    [[ ${#sorted[@]} -eq 0 ]] && continue
    parts_size=0
    for p in "${sorted[@]}"; do
      parts_size=$((parts_size + $(stat -c%s "$p" 2>/dev/null || echo 0)))
    done
    target_size=0
    [[ -e "$target" ]] && target_size="$(stat -c%s "$target" 2>/dev/null || echo 0)"
    if [[ ! -e "$target" || "$target_size" -lt "$parts_size" ]]; then
      cat "${sorted[@]}" > "$target"
      c_green "  ✓ $(basename "$target") ($(du -h "$target" | awk '{print $1}'))"
    fi
  done
fi

if [[ -d "$IMAGES_DIR" ]] && compgen -G "${IMAGES_DIR}/*.tar*" > /dev/null; then
  # Önce uygulama imajları, sonra kalan tüm arşivler (postgres16, dropt-api, …)
  declare -A _seen_img=()
  _load_queue=()
  for f in \
      "$IMAGES_DIR/ainew-backend.tar.gz" \
      "$IMAGES_DIR/ainew-frontend.tar.gz" \
      "$IMAGES_DIR"/*.tar.gz; do
    [[ -e "$f" ]] || continue
    case "$(basename "$f")" in
      ollama-models-*.tar.gz) continue ;;
    esac
    [[ -n "${_seen_img[$f]:-}" ]] && continue
    _seen_img[$f]=1
    _load_queue+=("$f")
  done
  for f in "${_load_queue[@]}"; do
    c_yellow "Yükleniyor: $(basename "$f")"
    if ! gunzip -c "$f" | docker load; then
      c_red "docker load başarısız: $f"
      DOCKER_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
      [[ -n "${DOCKER_ROOT:-}" ]] && mkdir -p "${DOCKER_ROOT}/tmp"
      c_yellow "Docker tmp düzeltildi; tekrar deneyin veya disk alanını kontrol edin."
      exit 1
    fi
  done
  for f in "$IMAGES_DIR"/*.tar; do
    [[ -e "$f" ]] || continue
    case "$(basename "$f")" in
      ollama-models-*.tar) continue ;;
    esac
    c_yellow "Yükleniyor: $(basename "$f")"
    if ! docker load -i "$f"; then
      c_red "docker load başarısız: $f"
      exit 1
    fi
  done
  c_green "İmajlar yüklendi."

  # Dropt compose varsa zorunlu imajları doğrula
  if grep -q 'docker-compose.dropt.yml' "$INSTALL_DIR/$COMPOSE_FILE" 2>/dev/null; then
    _missing=0
    for img in "postgres:16-alpine" "dropt-api:local"; do
      if ! docker image inspect "$img" >/dev/null 2>&1; then
        c_red "  eksik imaj (Dropt): $img"
        _missing=1
      else
        c_green "  ✓ $img"
      fi
    done
    if [[ "$_missing" -ne 0 ]]; then
      c_red "Dropt imajları eksik — images/postgres16.tar.gz ve dropt-api.tar.gz paketini kontrol edin."
      exit 1
    fi
  fi

  # with-ollama: embedding modeli volume'e
  if [[ -f "$INSTALL_DIR/WITH_OLLAMA" ]] || compgen -G "${IMAGES_DIR}/ollama-models-*.tar.gz" > /dev/null 2>&1; then
    step "Ollama embedding modeli güncelleniyor (with-ollama)"
    mkdir -p "$DATA_DIR/ollama"
    for mf in "${IMAGES_DIR}"/ollama-models-*.tar.gz; do
      [[ -e "$mf" ]] || continue
      c_yellow "Model: $(basename "$mf")"
      tar xzf "$mf" -C "$DATA_DIR/ollama"
    done
    chmod -R 777 "$DATA_DIR/ollama" 2>/dev/null || true
    set_env "OLLAMA_URL" "http://127.0.0.1:11434" "$INSTALL_DIR/$ENV_FILE"
    EMBED_FROM_MARKER="$(grep '^EMBED_MODEL=' "$INSTALL_DIR/WITH_OLLAMA" 2>/dev/null | head -1 | cut -d= -f2- || true)"
    set_env "OLLAMA_EMBED_MODEL" "${EMBED_FROM_MARKER:-nomic-embed-text}" "$INSTALL_DIR/$ENV_FILE"
  fi
elif [[ "${ALLOW_ONLINE_BUILD:-0}" == "1" ]]; then
  c_yellow "images/ yok — ALLOW_ONLINE_BUILD=1: kaynak derleniyor..."
  ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" -f docker-compose.build.yml build backend frontend )
else
  c_red "images/ yok veya boş — offline güncelleme yapılamaz."
  c_yellow "Tam paket kullanın (ainew-*-linux-amd64.tar.gz). Online: ALLOW_ONLINE_BUILD=1"
  exit 1
fi

step "Ollama runtime kontrol ediliyor"
ensure_ollama_runtime

# Eski imajları SİLME — rollback için docker'da kalsınlar.
c_yellow "Not: Eski imajlar (${OLD_BACKEND:-eski} / ${OLD_FRONTEND:-eski}) rollback için Docker'da bırakıldı."

# ── 5. Servisleri yeni imajlarla ayağa kaldır ───────────────────────────────
step "Servisler yeniden başlatılıyor (--no-build)"
cd "$INSTALL_DIR"
# Docker data-root tmp (load sonrası da güvenli)
if docker info >/dev/null 2>&1; then
  DOCKER_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
  [[ -n "${DOCKER_ROOT:-}" ]] && mkdir -p "${DOCKER_ROOT}/tmp"
fi
set -a; # shellcheck disable=SC1091
source "$ENV_FILE"
set +a

COMPOSE_PROFILES=()
# DİKKAT: Sadece WITH_OLLAMA marker dosyasının VARLIĞINA bakıp --profile ollama
# eklemek yeterli değil — ensure_ollama_runtime() indirme/docker-load hatası
# sırasında sessizce devam edip marker'ı silmiyor, bu yüzden imaj gerçekte
# yüklenmemiş olsa da profil eklenip "docker compose up" tüm çalıştırmayı
# "no such image: docker.io/ollama/ollama:latest" hatasıyla düşürüyordu (bkz.
# müşteri ortamı bulgusu: internet erişimi olmayan/podman tabanlı sunucuda
# runtime indirme başarısız oldu ama update yine ollama profilini etkinleştirip
# çöktü). Gerçek koşul: imaj docker/podman'da fiilen var mı?
if docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
  COMPOSE_PROFILES=(--profile ollama)
elif [[ -f "$INSTALL_DIR/WITH_OLLAMA" ]]; then
  c_red "with-ollama paketi ama ollama/ollama:latest imajı yüklenemedi (yukarıdaki 'Ollama runtime kontrol ediliyor' adımındaki hataya bakın — internet erişimi veya disk alanı sorunu olabilir)."
  c_yellow "Ollama profili BU ÇALIŞTIRMADA ATLANACAK — diğer servisler normal başlayacak (RAG embedding/Chat LLM devre dışı kalır)."
  c_yellow "İmajı air-gapped elle yükleme adımları: docs/INSTALL_RHEL.md §5.3. Sonra tekrar etkinleştirmek için:"
  c_yellow "  docker compose --profile ollama -f $COMPOSE_FILE up -d"
fi

if docker compose -f "$COMPOSE_FILE" up -d --help 2>&1 | grep -q -- '--pull'; then
  docker compose "${COMPOSE_PROFILES[@]}" -f "$COMPOSE_FILE" up -d --no-build --pull never
else
  docker compose "${COMPOSE_PROFILES[@]}" -f "$COMPOSE_FILE" up -d --no-build
fi

# Mevcut Postgres volume + .env şifresi: ALTER USER ile senkron
_MAIN_PG="$(grep '^POSTGRES_PASSWORD=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2-)"
if [[ -n "$_MAIN_PG" ]] && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'server_management_db'; then
  for _i in $(seq 1 20); do
    docker exec server_management_db pg_isready -U postgres >/dev/null 2>&1 && break
    sleep 1
  done
  docker exec server_management_db psql -U postgres -d postgres \
    -c "ALTER USER postgres WITH PASSWORD '${_MAIN_PG}';" >/dev/null 2>&1 \
    && c_green "ainew Postgres şifresi .env ile senkron." || true
fi
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'dropt_db'; then
  _MP="$(grep '^DROPT_POSTGRES_PASSWORD=' "$INSTALL_DIR/$ENV_FILE" | head -1 | cut -d= -f2-)"
  if [[ -n "$_MP" ]]; then
    for _i in $(seq 1 20); do
      docker exec dropt_db pg_isready -U dtt >/dev/null 2>&1 && break
      sleep 1
    done
    docker exec dropt_db psql -U dtt -d postgres -c "ALTER USER dtt WITH PASSWORD '${_MP}';" >/dev/null 2>&1 \
      && c_green "Dropt DB şifresi .env ile senkron." || true
  fi
fi
docker compose -f "$COMPOSE_FILE" --project-directory "$INSTALL_DIR" \
  up -d --no-build backend dropt-api dropt-worker 2>/dev/null || true

step "Sağlık kontrolü"
READY=0
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 3
done

echo
if [[ "$READY" -eq 1 ]]; then
  c_green "✔ Güncelleme tamamlandı: ${OLD_VERSION} → ${NEW_VERSION}"
else
  c_red "⚠ Backend henüz yanıt vermiyor."
  c_yellow "  Log: cd $INSTALL_DIR && docker compose -f $COMPOSE_FILE logs --tail=50 backend"
  c_yellow "  Geri dön: cd $INSTALL_DIR && sudo ./rollback-rhel.sh"
fi

echo
c_green "════════════════════════════════════════════════════════════════"
echo " Aktif sürüm  : $NEW_VERSION"
echo " Yedek        : $BACKUP_DIR"
echo " Geri dönüş   : cd $INSTALL_DIR && sudo ./rollback-rhel.sh"
echo "               (DB de geri alınacaksa: sudo ./rollback-rhel.sh --restore-db)"
if [[ ${#COMPOSE_PROFILES[@]} -gt 0 ]]; then
  echo " Ollama       : with-ollama — docker compose -f $COMPOSE_FILE --profile ollama ps ollama"
fi
c_green "════════════════════════════════════════════════════════════════"
echo
