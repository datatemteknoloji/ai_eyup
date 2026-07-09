#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# RHEL 9 kurulum betiği — AINE Altyapı Yönetim Platformu
#
# Kullanım:
#   sudo ./install-rhel.sh
#
# Bu betik idempotent'tir: tekrar çalıştırılırsa mevcut .env / sertifika
# dosyalarını korur, sadece eksik olanları tamamlar.
#
# Ne yapar:
#   1. Docker CE + Compose plugin kurulumu (yoksa)
#   2. /var/lib/server_management altında veri dizinleri
#   3. .env dosyası (SECRET_KEY, POSTGRES_PASSWORD, ADMIN_DEFAULT_PASSWORD,
#      CORS_ORIGINS otomatik üretilir/doldurulur)
#   4. Self-signed TLS sertifikası (frontend HTTPS için)
#   5. firewalld kuralları (80, 443, 9090, 9091)
#   6. Paket içinde önceden derlenmiş imaj varsa `docker load`, yoksa
#      kaynak koddan `docker compose build`
#   7. docker compose -f docker-compose.prod.yml up -d
#   8. Sağlık kontrolü + giriş bilgileri özeti
#
# Ollama modelleri (LLM ağırlıkları) bu pakete/imaja GÖMÜLMEZ — multi-GB
# oldukları için ayrı tutulur. Air-gapped (internet erişimi olmayan) bir
# kuruluma modelleri taşımak için, kaynak (internet erişimi olan) makinede
# önce modelleri `ollama pull` ile indirip scripts/export-ollama-models.sh
# ile dışa aktarın, tarball'ı bu sunucuya kopyalayın ve
# scripts/import-ollama-models.sh ile /var/lib/server_management/ollama
# altına geri yükleyin (ollama servisini başlatmadan önce).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DATA_DIR="${DATA_DIR:-/var/lib/server_management}"
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env"
IMAGES_DIR="./images"

c_green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red() { printf '\033[0;31m%s\033[0m\n' "$1"; }
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

if [[ $EUID -ne 0 ]]; then
  c_red "Bu betik root olarak çalıştırılmalı: sudo ./install-rhel.sh"
  exit 1
fi

if [[ ! -f /etc/redhat-release ]]; then
  c_yellow "Uyarı: /etc/redhat-release bulunamadı, RHEL/Rocky/AlmaLinux dışında bir sistem olabilir. Devam ediliyor..."
fi

# ── 1. Docker kurulumu ─────────────────────────────────────────────────────
step "Docker kontrol ediliyor"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  c_green "Docker ve Compose plugin zaten kurulu: $(docker --version)"
else
  step "Docker CE kuruluyor (RHEL 9 / dnf)"
  dnf -y install dnf-plugins-core
  dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
  dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  c_green "Docker kuruldu: $(docker --version)"
fi

# ── 2. Veri dizinleri ───────────────────────────────────────────────────────
step "Veri dizinleri oluşturuluyor: $DATA_DIR"
mkdir -p "$DATA_DIR"/{postgres,redis,chroma,repos,uploads,prometheus,certs,ollama}
# SELinux etiketleme docker-compose.prod.yml içindeki :Z bayrağı ile container
# başlatılırken otomatik yapılır; burada sadece dizinlerin var olması yeterli.

# postgres/redis hariç: bu dizinler kendi resmi imajlarının entrypoint'i
# tarafından (root olarak başlayıp doğru kullanıcıya chown edip düşen) otomatik
# düzeltiliyor. Ama backend (appuser, non-root) ve prometheus (nobody, non-root)
# imajları böyle bir self-heal yapmıyor — mkdir ile root:root oluşan bu
# dizinlere yazamayıp "Permission denied" ile çöküyorlar (chroma, repos,
# uploads, prometheus TSDB verisi). Ollama da genelde non-root çalışır.
# Bu host tek-amaçlı bir uygulama sunucusu olduğu için 777 kabul edilebilir.
chmod -R 777 "$DATA_DIR"/{chroma,repos,uploads,prometheus,ollama}

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
  if grep -q "^${key}=" "$ENV_FILE"; then
    # Sadece placeholder/boş değerleri doldur, elle girilmiş değerleri koru
    local current
    current="$(grep "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2-)"
    if [[ -z "$current" || "$current" == CHANGE_ME* || "$current" == GENERATE_* ]]; then
      sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    fi
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

fill_env_var "SECRET_KEY" "$(openssl rand -hex 32)"
fill_env_var "POSTGRES_PASSWORD" "$(openssl rand -hex 16)"
fill_env_var "ADMIN_DEFAULT_PASSWORD" "$(openssl rand -base64 12 | tr -d '=+/')"
fill_env_var "CORS_ORIGINS" "https://${PRIMARY_IP},http://${PRIMARY_IP}"
fill_env_var "DATA_DIR" "$DATA_DIR"

c_green "$ENV_FILE hazır (mevcut değerler korunur, sadece boş/varsayılanlar dolduruldu)."

# ── 4. Self-signed TLS sertifikası ──────────────────────────────────────────
step "TLS sertifikası kontrol ediliyor"
CERT="$DATA_DIR/certs/server.crt"
KEY="$DATA_DIR/certs/server.key"
if [[ -f "$CERT" && -f "$KEY" ]]; then
  c_green "Mevcut sertifika kullanılacak: $CERT"
else
  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$KEY" -out "$CERT" \
    -subj "/C=TR/O=AINE/CN=${PRIMARY_IP}" \
    -addext "subjectAltName=IP:${PRIMARY_IP},DNS:localhost" \
    2>/dev/null
  chmod 600 "$KEY"
  c_green "Self-signed sertifika üretildi (10 yıl geçerli). Kendi CA-imzalı sertifikanız varsa"
  c_yellow "  $CERT / $KEY dosyalarının üzerine yazıp servisi yeniden başlatabilirsiniz."
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

# ── 6. İmaj yükleme veya kaynaktan derleme ───────────────────────────────────
step "İmajlar hazırlanıyor"

# GitHub'ın LFS'siz 100MB dosya sınırı nedeniyle büyük imaj arşivleri
# (ör. ainew-backend.tar.gz.part01, .part02, ...) parçalara bölünmüş olarak
# depoda tutulur (bkz. scripts/build-distribution.sh). Kurulumdan önce, henüz
# birleştirilmemiş her parça grubunu tek dosyaya geri birleştir.
if compgen -G "${IMAGES_DIR}/*.tar.gz.part*" > /dev/null 2>&1; then
  c_yellow "Parçalanmış imaj arşivleri birleştiriliyor..."
  for part1 in "${IMAGES_DIR}"/*.tar.gz.part01; do
    [[ -e "$part1" ]] || continue
    target="${part1%.part01}"
    if [[ ! -e "$target" ]]; then
      cat "${target}".part* > "$target"
      c_green "  ✓ $(basename "$target")"
    fi
  done
fi

if [[ -d "$IMAGES_DIR" ]] && compgen -G "${IMAGES_DIR}/*.tar*" > /dev/null; then
  for f in "$IMAGES_DIR"/*.tar.gz; do
    [[ -e "$f" ]] || continue
    c_yellow "Yükleniyor: $f"
    gunzip -c "$f" | docker load
  done
  for f in "$IMAGES_DIR"/*.tar; do
    [[ -e "$f" ]] || continue
    c_yellow "Yükleniyor: $f"
    docker load -i "$f"
  done
  c_green "Önceden derlenmiş imajlar yüklendi (offline kurulum)."
else
  c_yellow "images/ dizini bulunamadı — kaynak koddan derleniyor (internet/registry erişimi gerekir)."
  docker compose -f "$COMPOSE_FILE" build
fi

# ── 7. Servisleri başlat ─────────────────────────────────────────────────────
step "Servisler başlatılıyor"
set -a; source "$ENV_FILE"; set +a
docker compose -f "$COMPOSE_FILE" up -d

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
c_yellow " ⚠ İlk girişten sonra Ayarlar > Kullanıcılar üzerinden admin parolasını değiştirin."
c_yellow " ⚠ .env dosyasını güvenli bir yerde yedekleyin — SECRET_KEY ve DB parolasını içerir."
echo
echo " Durum      : docker compose -f $COMPOSE_FILE ps"
echo " Loglar     : docker compose -f $COMPOSE_FILE logs -f backend"
echo " Durdurma   : docker compose -f $COMPOSE_FILE down"
echo
