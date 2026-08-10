#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# RHEL 9 kurulum betiği — Altyapı Yönetim Platformu
#
# Kullanım:
#   sudo ./install-rhel.sh
#   sudo ./install-rhel.sh --install-dir /data
#   sudo ./install-rhel.sh --ollama-files /root/ollama-runtime
#     (with-ollama paketinde, internet erişimi olmayan sunucularda: elle
#      indirilen ollama.tar.gz[.part*] + ollama-models-*.tar.gz dosyalarının
#      bulunduğu klasörü işaret eder — internete hiç çıkılmadan yüklenir)
#
# Bu betik idempotent'tir: tekrar çalıştırılırsa mevcut .env / sertifika
# dosyalarını korur, sadece eksik olanları tamamlar.
#
# Ne yapar:
#   1. Docker CE + Compose plugin kurulumu (yoksa)
#   2. Kurulum dizini seçimi (sorulur) — paket + tüm kalıcı veriler oraya kurulur
#   3. .env dosyası (SECRET_KEY, POSTGRES_PASSWORD otomatik; ADMIN_DEFAULT_PASSWORD=Kim13Sun;
#      CORS_ORIGINS otomatik üretilir/doldurulur)
#   4. Self-signed TLS sertifikası (frontend HTTPS için)
#   5. firewalld kuralları (80, 443, 9090, 9091)
#   6. Paket içindeki önceden derlenmiş imajları `docker load` eder (zorunlu offline)
#      — ainew-backend/frontend + opsiyonel dropt-api.tar.gz (Level 1 sidecar)
#   7. docker compose -f docker-compose.yml up -d --no-build
#      (pakette offline stack docker-compose.yml adıyla gelir; Dropt include;
#       registry/build yok; ALLOW_ONLINE_BUILD=1 opsiyonel)
#   8. Sağlık kontrolü + giriş bilgileri özeti
#
# Ollama modelleri (LLM ağırlıkları) bu pakete/imaja GÖMÜLMEZ — multi-GB
# oldukları için ayrı tutulur. Air-gapped (internet erişimi olmayan) bir
# kuruluma modelleri taşımak için, kaynak (internet erişimi olan) makinede
# önce modelleri `ollama pull` ile indirip scripts/export-ollama-models.sh
# ile dışa aktarın, tarball'ı bu sunucuya kopyalayın ve
# scripts/import-ollama-models.sh ile kurulum dizininizin altındaki
# <INSTALL_DIR>/data/ollama içine geri yükleyin (ollama servisini başlatmadan önce).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Müşteri paketinde tek dosya: docker-compose.yml (offline stack).
# Repo kökünde hem geliştirme docker-compose.yml hem docker-compose.prod.yml
# varsa prod şablonu tercih edilir (yanlışlıkla dev compose ile kurulum olmasın).
if [[ -f "docker-compose.prod.yml" ]]; then
  COMPOSE_FILE="docker-compose.prod.yml"
else
  COMPOSE_FILE="docker-compose.yml"
fi
ENV_FILE=".env"
IMAGES_DIR="./images"
DEFAULT_INSTALL_DIR="/data"

c_green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red() { printf '\033[0;31m%s\033[0m\n' "$1"; }
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

OLLAMA_FILES_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --ollama-files) OLLAMA_FILES_DIR="$(realpath -m "$2")"; shift 2 ;;
    -h|--help)
      sed -n '2,34p' "$0"
      exit 0
      ;;
    *) c_red "Bilinmeyen argüman: $1 (bkz. --help)"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  c_red "Bu betik root olarak çalıştırılmalı: sudo ./install-rhel.sh"
  exit 1
fi

if [[ ! -f /etc/redhat-release ]]; then
  c_yellow "Uyarı: /etc/redhat-release bulunamadı, RHEL/Rocky/AlmaLinux dışında bir sistem olabilir. Devam ediliyor..."
fi

# ── 0. Kurulum dizini ────────────────────────────────────────────────────────
# Uygulama paketinin TAMAMI (kaynak/derleme dosyaları, imajlar, scriptler) VE
# kalıcı veriler (DB, Redis, Chroma, yüklenen dosyalar, Prometheus, sertifikalar,
# Ollama modelleri) TEK bir kök dizin altında toplanır — /var/lib gibi sistem
# dizinlerine dağılmaz. Zaten kurulmuşsa (bu dizinde .env varsa) tekrar sorulmaz.
if [[ -f "$SCRIPT_DIR/$ENV_FILE" ]] && grep -q '^DATA_DIR=' "$SCRIPT_DIR/$ENV_FILE" 2>/dev/null; then
  INSTALL_DIR="$SCRIPT_DIR"
  DATA_DIR="$(grep '^DATA_DIR=' "$SCRIPT_DIR/$ENV_FILE" | head -1 | cut -d= -f2-)"
  c_green "Mevcut kurulum tespit edildi, kurulum dizini: $INSTALL_DIR"
else
  if [[ -z "${INSTALL_DIR:-}" ]]; then
    if [[ -t 0 ]]; then
      echo
      read -rp "Kurulum dizini — uygulamanın TAMAMI (paket + veritabanı + yüklenen dosyalar + modeller) buraya kurulacak, mutlak yol girin [${DEFAULT_INSTALL_DIR}]: " INSTALL_DIR
      INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
    else
      INSTALL_DIR="$DEFAULT_INSTALL_DIR"
      c_yellow "İnteraktif olmayan çalıştırma: varsayılan kurulum dizini kullanılıyor: $INSTALL_DIR"
    fi
  fi
  INSTALL_DIR="$(realpath -m "$INSTALL_DIR")"

  if [[ "$INSTALL_DIR" != "$SCRIPT_DIR" ]]; then
    step "Uygulama paketi kopyalanıyor: $SCRIPT_DIR -> $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --exclude '.git' "$SCRIPT_DIR"/ "$INSTALL_DIR"/
    else
      cp -a "$SCRIPT_DIR"/. "$INSTALL_DIR"/
    fi
    c_green "Paket kopyalandı: $INSTALL_DIR"
    cd "$INSTALL_DIR"
    SCRIPT_DIR="$INSTALL_DIR"
  fi
  DATA_DIR="$INSTALL_DIR/data"
fi

# ── 1. Docker kurulumu ─────────────────────────────────────────────────────
step "Docker kontrol ediliyor"
DOCKER_JUST_INSTALLED=0
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  c_green "Docker ve Compose plugin zaten kurulu: $(docker --version)"
else
  step "Docker CE kuruluyor (RHEL 9 / dnf)"
  dnf -y install dnf-plugins-core
  dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
  dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  DOCKER_JUST_INSTALLED=1
  c_green "Docker kuruldu: $(docker --version)"
fi

# Tüm uygulama + Docker image/volume verisi /data altında kalsın
DOCKER_DATA_ROOT="/data/docker"
mkdir -p "$DOCKER_DATA_ROOT/tmp"
if [[ "$DOCKER_JUST_INSTALLED" == "1" ]]; then
  step "Docker data-root → $DOCKER_DATA_ROOT (tek disk politikası)"
  mkdir -p /etc/docker
  if [[ ! -f /etc/docker/daemon.json ]]; then
    cat > /etc/docker/daemon.json <<EOF
{
  "data-root": "${DOCKER_DATA_ROOT}",
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" }
}
EOF
  elif ! grep -q '"data-root"' /etc/docker/daemon.json 2>/dev/null; then
    python3 - "$DOCKER_DATA_ROOT" <<'PY' || true
import json, sys
root = sys.argv[1]
path = "/etc/docker/daemon.json"
try:
    with open(path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}
if not isinstance(cfg, dict):
    cfg = {}
cfg["data-root"] = root
cfg.setdefault("log-driver", "json-file")
cfg.setdefault("log-opts", {"max-size": "50m", "max-file": "3"})
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY
  fi
  systemctl restart docker
  c_green "Docker data-root: $DOCKER_DATA_ROOT"
elif docker info >/dev/null 2>&1; then
  CURRENT_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
  if [[ -n "$CURRENT_ROOT" && "$CURRENT_ROOT" != "$DOCKER_DATA_ROOT" ]]; then
    c_yellow "Uyarı: Docker data-root şu an $CURRENT_ROOT — tek-disk için /etc/docker/daemon.json içinde \"data-root\": \"$DOCKER_DATA_ROOT\" önerilir (mevcut kurulumda otomatik taşınmadı)."
  fi
fi

# Docker veri kökü (data-root) eksik tmp yüzünden `docker load` düşmesin
if docker info >/dev/null 2>&1; then
  DOCKER_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
  if [[ -n "${DOCKER_ROOT:-}" ]]; then
    mkdir -p "${DOCKER_ROOT}/tmp"
  fi
else
  c_red "Docker çalışmıyor veya erişilemiyor. 'systemctl status docker' kontrol edin."
  exit 1
fi

# ── 2. Veri dizinleri ───────────────────────────────────────────────────────
step "Veri dizinleri oluşturuluyor: $DATA_DIR"
mkdir -p "$DATA_DIR"/{postgres,redis,chroma,repos,uploads,updates,prometheus,certs,ollama}
mkdir -p "$DATA_DIR/dropt"/{postgres,redis,ssh-keys,artifacts,keytabs,certs,rpms}
mkdir -p "$DATA_DIR/updates"/{incoming,prepared,bin}
# GUI platform güncelleme wrapper'ı
if [[ -f "$SCRIPT_DIR/ainew-apply-update.sh" ]]; then
  cp -a "$SCRIPT_DIR/ainew-apply-update.sh" "$DATA_DIR/updates/bin/ainew-apply-update.sh"
  cp -a "$SCRIPT_DIR/ainew-apply-update.sh" "$INSTALL_DIR/ainew-apply-update.sh" 2>/dev/null || true
  chmod +x "$DATA_DIR/updates/bin/ainew-apply-update.sh" "$INSTALL_DIR/ainew-apply-update.sh" 2>/dev/null || true
fi
# SELinux etiketleme docker-compose.prod.yml içindeki :Z bayrağı ile container
# başlatılırken otomatik yapılır; burada sadece dizinlerin var olması yeterli.

# postgres/redis hariç: bu dizinler kendi resmi imajlarının entrypoint'i
# tarafından (root olarak başlayıp doğru kullanıcıya chown edip düşen) otomatik
# düzeltiliyor. Ama backend (appuser, non-root) ve prometheus (nobody, non-root)
# imajları böyle bir self-heal yapmıyor — mkdir ile root:root oluşan bu
# dizinlere yazamayıp "Permission denied" ile çöküyorlar (chroma, repos,
# uploads, prometheus TSDB verisi). Ollama da genelde non-root çalışır.
# Bu host tek-amaçlı bir uygulama sunucusu olduğu için 777 kabul edilebilir.
chmod -R 777 "$DATA_DIR"/{chroma,repos,uploads,updates,prometheus,ollama}

# prometheus/targets/*.json: backend (appuser) yazıyor, prometheus (nobody)
# okuyor — ikisi de farklı non-root kullanıcı, ikisinin de erişebilmesi için
# aynı sebeple 777.
chmod -R 777 "$SCRIPT_DIR/prometheus/targets" 2>/dev/null || true

c_green "Tamam."

# ── 3. .env dosyası ─────────────────────────────────────────────────────────
step ".env dosyası hazırlanıyor"
PRIMARY_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -z "$PRIMARY_IP" ]] && PRIMARY_IP="localhost"

if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.example "$ENV_FILE"
  c_yellow "$ENV_FILE oluşturuldu (.env.example üzerinden)."
fi

fill_env_var() {
  local key="$1" value="$2"
  # Placeholder / boş = doldur (GENERATE_WITH_* dahil). Elle girilmiş gerçek sırları koru.
  _is_placeholder_val() {
    local v="${1:-}"
    [[ -z "$v" ]] && return 0
    local u
    u="$(printf '%s' "$v" | tr '[:lower:]' '[:upper:]')"
    [[ "$u" == CHANGE_ME* || "$u" == GENERATE_* || "$u" == REPLACE-* || "$u" == TODO* || "$u" == YOUR_* ]] && return 0
    return 1
  }
  if grep -q "^${key}=" "$ENV_FILE"; then
    local current
    current="$(grep "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2-)"
    if _is_placeholder_val "$current"; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    fi
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

# Mevcut değeri her zaman paket sürümüyle değiştir (imaj etiketleri için zorunlu)
set_env_var() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    # İlk satırı güncelle; aynı key'in tekrarlarını sil (çift BACKEND_IMAGE vb.)
    awk -v k="$key" -v v="$value" '
      index($0, k "=") == 1 {
        if (!seen++) { print k "=" v }
        next
      }
      { print }
    ' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

fill_env_var "SECRET_KEY" "$(openssl rand -hex 32)"
fill_env_var "POSTGRES_PASSWORD" "$(openssl rand -hex 16)"
# İlk kurulum admin parolası sabit — müşteri/operasyon bilinen değerle giriş yapsın
fill_env_var "ADMIN_DEFAULT_PASSWORD" "Kim13Sun"
fill_env_var "CORS_ORIGINS" "https://${PRIMARY_IP},http://${PRIMARY_IP}"
fill_env_var "DATA_DIR" "$DATA_DIR"
fill_env_var "AINEW_INSTALL_DIR" "$INSTALL_DIR"
fill_env_var "AINEW_DATA_DIR" "$DATA_DIR"
fill_env_var "RAG_CHROMA_PATH" "/app/chroma"
fill_env_var "PLATFORM_UPDATE_ENABLED" "true"

# Level 1 / Dropt sidecar secrets
fill_env_var "AINEW_BRIDGE_SECRET" "$(openssl rand -hex 24)"
fill_env_var "DROPT_API_URL" "http://127.0.0.1:8001"
fill_env_var "DROPT_POSTGRES_USER" "dtt"
fill_env_var "DROPT_POSTGRES_PASSWORD" "$(openssl rand -hex 16)"
fill_env_var "DROPT_POSTGRES_DB" "dttportal"
fill_env_var "DROPT_API_IMAGE" "dropt-api:local"
fill_env_var "DROPT_PULL_POLICY" "never"

# dropt/.env (Fernet + JWT) — ana .env ile köprü secret paylaşır
if [[ ! -f dropt/.env ]]; then
  if [[ -f dropt/.env.example ]]; then
    cp dropt/.env.example dropt/.env
  else
    touch dropt/.env
  fi
fi
_dropt_fill() {
  local key="$1" value="$2" f="dropt/.env"
  if grep -q "^${key}=" "$f" 2>/dev/null; then
    local cur
    cur="$(grep "^${key}=" "$f" | head -1 | cut -d= -f2-)"
    if [[ -z "$cur" || "$cur" == change-me* || "$cur" == replace-* || "$cur" == admin123 ]]; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$f"
    fi
  else
    echo "${key}=${value}" >> "$f"
  fi
}
_DROPT_PG="$(grep '^DROPT_POSTGRES_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
_BRIDGE="$(grep '^AINEW_BRIDGE_SECRET=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
_dropt_fill "POSTGRES_USER" "dtt"
_dropt_fill "POSTGRES_PASSWORD" "${_DROPT_PG}"
_dropt_fill "POSTGRES_DB" "dttportal"
_dropt_fill "FERNET_KEY" "$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || openssl rand -base64 32)"
_dropt_fill "JWT_SECRET" "$(openssl rand -hex 32)"
_dropt_fill "AINEW_BRIDGE_SECRET" "${_BRIDGE}"
_dropt_fill "CORS_ORIGINS" "https://${PRIMARY_IP},http://${PRIMARY_IP}"
_dropt_fill "ADMIN_PASSWORD" "$(openssl rand -base64 12 | tr -d '=+/')"
_dropt_fill "RESET_ADMIN_PASSWORD" "false"
chmod 600 dropt/.env 2>/dev/null || true
chmod 600 "$ENV_FILE" 2>/dev/null || true

# VERSION dosyası kanonik — .env.example eski etiket taşıyabilir (update-rhel ile aynı).
# Eski .env'de kalan etiketler korunursa load yeni tag yapsa bile "eksik imaj" hatası çıkar.
APP_VERSION="$(tr -d '[:space:]' < VERSION 2>/dev/null || true)"
[[ -z "$APP_VERSION" ]] && APP_VERSION="latest"
set_env_var "BACKEND_IMAGE" "ainew-backend:${APP_VERSION}"
set_env_var "FRONTEND_IMAGE" "ainew-frontend:${APP_VERSION}"
set_env_var "APP_VERSION" "$APP_VERSION"
c_green "İmaj etiketleri paket sürümüne sabitlendi: ainew-backend:${APP_VERSION} / ainew-frontend:${APP_VERSION}"
fill_env_var "OLLAMA_URL" "http://127.0.0.1:11434"
fill_env_var "OLLAMA_EMBED_MODEL" "nomic-embed-text"

c_green "$ENV_FILE hazır (mevcut değerler korunur, sadece boş/varsayılanlar dolduruldu)."

# ── 4. Self-signed TLS sertifikası ──────────────────────────────────────────
step "TLS sertifikası kontrol ediliyor"
CERT="$DATA_DIR/certs/server.crt"
KEY="$DATA_DIR/certs/server.key"
mkdir -p "$DATA_DIR/certs"
if [[ -f "$CERT" && -f "$KEY" ]]; then
  c_green "Mevcut sertifika kullanılacak: $CERT"
else
  if ! command -v openssl >/dev/null 2>&1; then
    c_red "openssl yok — TLS sertifikası üretilemedi."
    c_yellow "Kurun: dnf install -y openssl  (frontend entrypoint de üretebilir; yine de host'ta openssl önerilir)"
    exit 1
  fi
  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$KEY" -out "$CERT" \
    -subj "/C=TR/O=ServerManagement/CN=${PRIMARY_IP}" \
    -addext "subjectAltName=IP:${PRIMARY_IP},DNS:localhost" \
    2>/dev/null
  chmod 600 "$KEY"
  chmod 644 "$CERT" 2>/dev/null || true
  # Backend TLS UI (appuser) yazabilsin diye dizin sahipliği
  chown -R 100:102 "$DATA_DIR/certs" 2>/dev/null || true
  c_green "Self-signed sertifika üretildi (10 yıl geçerli). Kendi CA-imzalı sertifikanız varsa"
  c_yellow "  $CERT / $KEY dosyalarının üzerine yazıp servisi yeniden başlatabilirsiniz."
  c_yellow "  veya Ayarlar → Güvenlik → TLS / HTTPS üzerinden yükleyebilirsiniz."
fi
if [[ ! -f "$CERT" || ! -f "$KEY" ]]; then
  c_red "TLS sertifikası eksik: $CERT / $KEY"
  exit 1
fi

# ── 5. firewalld ─────────────────────────────────────────────────────────────
step "firewalld kuralları"
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  for port in 80/tcp 443/tcp 9090/tcp 9091/tcp; do
    firewall-cmd --permanent --add-port="$port" >/dev/null 2>&1 || true
  done
  firewall-cmd --reload >/dev/null 2>&1 || true
  c_green "80, 443, 9090, 9091 portları açıldı."
else
  c_yellow "firewalld aktif değil veya kurulu değil, bu adım atlandı."
fi

# ── 6. İmaj yükleme (offline) ────────────────────────────────────────────────
step "İmajlar hazırlanıyor"

merge_image_parts() {
  if compgen -G "${IMAGES_DIR}/*.tar.gz.part*" > /dev/null 2>&1; then
    c_yellow "Parçalanmış imaj arşivleri birleştiriliyor..."
    local part1 target parts_size target_size sorted
    for part1 in "${IMAGES_DIR}"/*.tar.gz.part01; do
      [[ -e "$part1" ]] || continue
      target="${part1%.part01}"
      # Lexical değil versiyon sıralı birleştir (part01…part10)
      mapfile -t sorted < <(ls -1 "${target}".part* 2>/dev/null | sort -V)
      [[ ${#sorted[@]} -eq 0 ]] && continue
      parts_size=0
      local p
      for p in "${sorted[@]}"; do
        parts_size=$((parts_size + $(stat -c%s "$p" 2>/dev/null || echo 0)))
      done
      target_size=0
      [[ -e "$target" ]] && target_size="$(stat -c%s "$target" 2>/dev/null || echo 0)"
      # Eksik/bozuk birleşik dosyayı yeniden üret
      if [[ ! -e "$target" || "$target_size" -lt "$parts_size" ]]; then
        cat "${sorted[@]}" > "$target"
        c_green "  ✓ $(basename "$target") ($(du -h "$target" | awk '{print $1}'))"
      else
        c_yellow "  · $(basename "$target") zaten var — atlandı"
      fi
    done
  fi
}

load_all_images() {
  local f loaded=0
  local -A seen=()
  # Önce uygulama imajları (disk dolarsa en azından backend/frontend yüklensin)
  local queue=()
  for f in \
      "$IMAGES_DIR/ainew-backend.tar.gz" \
      "$IMAGES_DIR/ainew-frontend.tar.gz" \
      "$IMAGES_DIR"/*.tar.gz; do
    [[ -e "$f" ]] || continue
    case "$(basename "$f")" in
      ollama-models-*.tar.gz) continue ;;
    esac
    [[ -n "${seen[$f]:-}" ]] && continue
    seen[$f]=1
    queue+=("$f")
  done
  for f in "${queue[@]}"; do
    c_yellow "Yükleniyor: $f"
    if ! gunzip -c "$f" | docker load; then
      c_red "docker load başarısız: $f"
      c_yellow "Kontrol: Docker data-root tmp dizini, disk doluluğu (df -h), 'docker info'"
      return 1
    fi
    loaded=$((loaded + 1))
  done
  for f in "$IMAGES_DIR"/*.tar; do
    [[ -e "$f" ]] || continue
    case "$(basename "$f")" in
      ollama-models-*.tar) continue ;;
    esac
    c_yellow "Yükleniyor: $f"
    if ! docker load -i "$f"; then
      c_red "docker load başarısız: $f"
      return 1
    fi
    loaded=$((loaded + 1))
  done
  [[ "$loaded" -gt 0 ]]
}

# Paketten yüklenen ainew etiketini .env ile hizala; başka tag varsa retag et
ensure_ainew_tags() {
  local be fe repo tag any
  be="$(grep '^BACKEND_IMAGE=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  fe="$(grep '^FRONTEND_IMAGE=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  be="${be:-ainew-backend:${APP_VERSION:-latest}}"
  fe="${fe:-ainew-frontend:${APP_VERSION:-latest}}"
  for img in "$be" "$fe"; do
    if docker image inspect "$img" >/dev/null 2>&1; then
      continue
    fi
    repo="${img%%:*}"
    tag="${img##*:}"
    any="$(docker images --format '{{.Repository}}:{{.Tag}}' "$repo" 2>/dev/null | grep -v '<none>' | head -1 || true)"
    if [[ -n "$any" ]]; then
      c_yellow "  retag: $any → $img"
      docker tag "$any" "$img"
      docker tag "$any" "${repo}:latest" 2>/dev/null || true
    fi
  done
}

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
  [[ -f ./WITH_OLLAMA ]] || return 0
  local release_base embed_model cache_dir
  release_base="$(grep '^OLLAMA_RUNTIME_BASE_URL=' ./WITH_OLLAMA 2>/dev/null | head -1 | cut -d= -f2- || true)"
  embed_model="$(grep '^EMBED_MODEL=' ./WITH_OLLAMA 2>/dev/null | head -1 | cut -d= -f2- || true)"
  embed_model="${embed_model:-nomic-embed-text}"
  cache_dir="$DATA_DIR/.ollama-runtime-cache"

  if docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
    c_green "  ✓ ollama/ollama:latest zaten yüklü — indirme atlandı."
  elif compgen -G "${IMAGES_DIR}/ollama.tar.gz*" > /dev/null 2>&1; then
    c_yellow "  · ollama/ollama:latest paket içinde gömülü — ayrıca indirme yapılmayacak (load_all_images yükleyecek)."
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
      c_yellow "  İnternetsiz kurulum için: sudo ./install-rhel.sh --ollama-files <dizin>"
    fi
  fi

  if [[ -d "$DATA_DIR/ollama/models" ]] && find "$DATA_DIR/ollama/models" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
    c_green "  ✓ Embedding modeli ($embed_model) zaten diskte — indirme atlandı."
  elif compgen -G "${IMAGES_DIR}/ollama-models-*.tar.gz*" > /dev/null 2>&1; then
    : # paket içinde gömülü — sonraki adım (with-ollama model açma) bunu işleyecek
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
      c_yellow "  İnternetsiz kurulum için: sudo ./install-rhel.sh --ollama-files <dizin>"
    fi
  fi
}

require_local_images() {
  local be fe
  be="$(grep '^BACKEND_IMAGE=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  fe="$(grep '^FRONTEND_IMAGE=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  be="${be:-ainew-backend:latest}"
  fe="${fe:-ainew-frontend:latest}"
  local missing=0 img
  local required=(
    "$be" "$fe"
    "timescale/timescaledb:2.17.2-pg15"
    "redis:7-alpine"
    "prom/prometheus:v2.55.1"
    "prom/pushgateway:v1.11.0"
    "postgres:16-alpine"
    "dropt-api:local"
  )
  if [[ -f ./WITH_OLLAMA ]] || compgen -G "${IMAGES_DIR}/ollama.tar.gz*" > /dev/null 2>&1; then
    required+=("ollama/ollama:latest")
  fi
  for img in "${required[@]}"; do
    if ! docker image inspect "$img" >/dev/null 2>&1; then
      c_red "  eksik imaj: $img"
      missing=1
    else
      c_green "  ✓ $img"
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    c_yellow "Docker'daki ainew imajları:"
    docker images --format '  {{.Repository}}:{{.Tag}}' 2>/dev/null | grep '^  ainew-' || c_yellow "  (yok)"
    c_yellow "Onarım: sudo ./fix-load-ainew-images.sh"
  fi
  [[ "$missing" -eq 0 ]]
}

merge_image_parts

HAS_ARCHIVES=0
if [[ -d "$IMAGES_DIR" ]] && compgen -G "${IMAGES_DIR}/*.tar*" > /dev/null; then
  HAS_ARCHIVES=1
fi

if [[ "$HAS_ARCHIVES" -eq 1 ]]; then
  # ainew arşivleri (birleşik veya parçalı) zorunlu
  if [[ ! -e "$IMAGES_DIR/ainew-backend.tar.gz" && ! -e "$IMAGES_DIR/ainew-backend.tar.gz.part01" ]]; then
    c_red "images/ içinde ainew-backend.tar.gz (veya .part*) yok — paket eksik/bozuk."
    ls -la "$IMAGES_DIR" || true
    exit 1
  fi
  if [[ ! -e "$IMAGES_DIR/ainew-frontend.tar.gz" && ! -e "$IMAGES_DIR/ainew-frontend.tar.gz.part01" ]]; then
    c_red "images/ içinde ainew-frontend.tar.gz (veya .part*) yok — paket eksik/bozuk."
    ls -la "$IMAGES_DIR" || true
    exit 1
  fi
  if ! load_all_images; then
    c_red "İmaj yükleme başarısız."
    exit 1
  fi
  c_green "Önceden derlenmiş imajlar yüklendi (offline kurulum)."
elif [[ "${ALLOW_ONLINE_BUILD:-0}" == "1" ]]; then
  c_yellow "images/ yok — ALLOW_ONLINE_BUILD=1: kaynak derleniyor (registry gerekir)..."
  docker compose -f "$COMPOSE_FILE" -f docker-compose.build.yml build
else
  c_red "images/ altında *.tar.gz bulunamadı — offline kurulum imkansız."
  c_yellow "Doğru paket: Releases → ainew-<sürüm>-linux-amd64.tar.gz (images/ dahildir)."
  c_yellow "Code→Download ZIP / git clone (--no-images) bu kurulum için yeterli değildir."
  c_yellow "İnternet erişimi varsa: ALLOW_ONLINE_BUILD=1 sudo ./install-rhel.sh"
  exit 1
fi

step "Ollama runtime kontrol ediliyor"
ensure_ollama_runtime

step "Yerel imajlar doğrulanıyor"
ensure_ainew_tags
if ! require_local_images; then
  if [[ "${ALLOW_ONLINE_BUILD:-0}" == "1" ]]; then
    c_yellow "Eksik imajlar var — online build denenecek..."
    docker compose -f "$COMPOSE_FILE" -f docker-compose.build.yml build
  else
    c_red "Zorunlu imajlar Docker'da yok. load başarısız olmuş olabilir."
    exit 1
  fi
fi

# ── 7. Servisleri başlat (asla registry pull / build yok) ───────────────────
step "Servisler başlatılıyor (--no-build)"
set -a; source "$ENV_FILE"; set +a

WITH_OLLAMA_PKG=0
if [[ -f ./WITH_OLLAMA ]] || compgen -G "${IMAGES_DIR}/ollama.tar.gz*" > /dev/null 2>&1 \
   || compgen -G "${IMAGES_DIR}/ollama-models-*.tar.gz*" > /dev/null 2>&1; then
  WITH_OLLAMA_PKG=1
fi

# with-ollama paketi: nomic-embed-text modelini DATA_DIR/ollama altına aç
if [[ "$WITH_OLLAMA_PKG" -eq 1 ]]; then
  step "Ollama embedding modeli hazırlanıyor (with-ollama)"
  mkdir -p "$DATA_DIR/ollama"
  # Parçalanmış model arşivlerini birleştir
  for part1 in "${IMAGES_DIR}"/ollama-models-*.tar.gz.part01; do
    [[ -e "$part1" ]] || continue
    target="${part1%.part01}"
    if [[ ! -e "$target" ]]; then
      cat "${target}".part* > "$target"
      c_green "  ✓ $(basename "$target")"
    fi
  done
  for mf in "${IMAGES_DIR}"/ollama-models-*.tar.gz; do
    [[ -e "$mf" ]] || continue
    c_yellow "Model içeri aktarılıyor: $(basename "$mf") → $DATA_DIR/ollama"
    tar xzf "$mf" -C "$DATA_DIR/ollama"
  done
  chmod -R 777 "$DATA_DIR/ollama" 2>/dev/null || true
  EMBED_FROM_MARKER="$(grep '^EMBED_MODEL=' ./WITH_OLLAMA 2>/dev/null | head -1 | cut -d= -f2- || true)"
  fill_env_var "OLLAMA_EMBED_MODEL" "${EMBED_FROM_MARKER:-nomic-embed-text}"
  fill_env_var "OLLAMA_URL" "http://127.0.0.1:11434"
  set -a; source "$ENV_FILE"; set +a
fi

COMPOSE_PROFILES=()
# DİKKAT: WITH_OLLAMA_PKG=1 (paket türü) yalnızca "with-ollama paketi indirildi"
# demektir — ensure_ollama_runtime() ağ/disk hatasıyla sessizce başarısız
# olabilir (marker dosyası silinmez). Bu durumda --profile ollama'yı yine de
# eklemek "docker compose up" tüm çalıştırmayı "no such image:
# docker.io/ollama/ollama:latest" hatasıyla düşürüyordu (bkz. müşteri ortamı
# bulgusu: internet erişimi olmayan/podman tabanlı sunucuda runtime indirme
# başarısız oldu). Gerçek koşul: imaj docker/podman'da fiilen var mı?
if [[ "$WITH_OLLAMA_PKG" -eq 1 ]]; then
  if docker image inspect ollama/ollama:latest >/dev/null 2>&1; then
    COMPOSE_PROFILES=(--profile ollama)
    c_yellow "with-ollama paketi: Ollama profili etkin."
  else
    c_red "with-ollama paketi ama ollama/ollama:latest imajı yüklenemedi (yukarıdaki 'Ollama imajı indiriliyor' adımındaki hataya bakın — internet erişimi veya disk alanı sorunu olabilir)."
    c_yellow "Ollama profili BU ÇALIŞTIRMADA ATLANACAK — diğer servisler normal başlayacak (RAG embedding/Chat LLM devre dışı kalır)."
    c_yellow "İmajı air-gapped elle yükleme adımları: docs/INSTALL_RHEL.md §5.3. Sonra tekrar etkinleştirmek için:"
    c_yellow "  docker compose --profile ollama -f $COMPOSE_FILE up -d"
  fi
fi

# Compose v2: --pull never desteklenirse kullan; eski sürümlerde sadece --no-build
if docker compose -f "$COMPOSE_FILE" up -d --help 2>&1 | grep -q -- '--pull'; then
  docker compose "${COMPOSE_PROFILES[@]}" -f "$COMPOSE_FILE" up -d --no-build --pull never
else
  docker compose "${COMPOSE_PROFILES[@]}" -f "$COMPOSE_FILE" up -d --no-build
fi

if [[ ${#COMPOSE_PROFILES[@]} -gt 0 ]]; then
  step "Ollama embedding sağlık kontrolü"
  EMBED_MODEL="$(grep '^OLLAMA_EMBED_MODEL=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
  OLLAMA_OK=0
  for i in $(seq 1 45); do
    if curl -sf --max-time 3 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
      OLLAMA_OK=1
      break
    fi
    sleep 2
  done
  if [[ "$OLLAMA_OK" -eq 1 ]]; then
    c_green "✔ Ollama hazır (http://127.0.0.1:11434)"
    if docker exec server_management_ollama ollama list 2>/dev/null | grep -qi "${EMBED_MODEL%%:*}"; then
      c_green "✔ Embedding modeli listede: $EMBED_MODEL"
    else
      c_yellow "⚠ $EMBED_MODEL listede görünmüyor — volume path / import kontrol edin."
      c_yellow "  docker exec server_management_ollama ollama list"
    fi
  else
    c_yellow "⚠ Ollama henüz yanıt vermiyor. 'docker compose -f $COMPOSE_FILE --profile ollama logs -f ollama'"
  fi
fi

# ── 8. Sağlık kontrolü ────────────────────────────────────────────────────────
step "Sağlık kontrolü (backend ısınıyor, ~30-60 sn sürebilir)"
READY=0
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 3
done

echo
if [[ "$READY" -eq 1 ]]; then
  c_green "✔ Backend hazır."
else
  c_yellow "⚠ Backend henüz yanıt vermiyor. 'docker compose -f $COMPOSE_FILE logs -f backend' ile kontrol edin."
fi

ADMIN_PW="$(grep '^ADMIN_DEFAULT_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
echo
c_green "════════════════════════════════════════════════════════════════"
c_green " Kurulum tamamlandı!"
c_green "════════════════════════════════════════════════════════════════"
echo " Arayüz     : https://${PRIMARY_IP}  (self-signed sertifika — tarayıcı uyarısı normaldir)"
echo " Kullanıcı  : admin"
echo " Parola     : ${ADMIN_PW}"
echo
echo " Kurulum dizini : $INSTALL_DIR  (paket + $ENV_FILE)"
echo " Veri dizini    : $DATA_DIR  (DB, Redis, Chroma, uploads, updates, certs, Ollama)"
echo " Docker data    : ${DOCKER_DATA_ROOT:-/data/docker}  (imajlar/volume'ler — tek disk)"
if [[ "$WITH_OLLAMA_PKG" -eq 1 ]]; then
  echo " Ollama        : with-ollama paketi — RAG embedding (${EMBED_MODEL:-nomic-embed-text}) dahil"
fi
echo
c_yellow " ⚠ İlk girişten sonra Ayarlar > Kullanıcılar üzerinden admin parolasını değiştirin."
c_yellow " ⚠ .env dosyasını güvenli bir yerde yedekleyin — SECRET_KEY ve DB parolasını içerir."
echo
echo " Durum      : docker compose -f $COMPOSE_FILE ps"
if [[ "$WITH_OLLAMA_PKG" -eq 1 ]]; then
  echo " Ollama     : docker compose -f $COMPOSE_FILE --profile ollama ps ollama"
fi
echo " Loglar     : docker compose -f $COMPOSE_FILE logs -f backend"
echo " Durdurma   : docker compose -f $COMPOSE_FILE down"
echo
