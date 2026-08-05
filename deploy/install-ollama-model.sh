#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# install-ollama-model.sh — Mevcut bir kuruluma EK bir Ollama modeli
# (chat modeli veya embedding modeli) air-gapped/internetsiz olarak ekler.
#
# install-ollama-runtime.sh / install-rhel.sh'in "--ollama-files" akışı yalnızca
# TEK bir embedding modelini (nomic-embed-text) kurulumla birlikte kurmak için
# tasarlanmıştı ve $DATA_DIR/ollama/models altında HERHANGİ bir model varsa
# tüm adımı atlar. Bu betik bağımsızdır: zaten kurulu bir sisteme, kurulu
# modellerden bağımsız olarak, YALNIZCA belirtilen modeli (varsa daha önce
# kurulmadıysa) ekler — ör. GPT-OSS 20B gibi büyük bir chat modelini sonradan
# eklemek için.
#
# Kullanım:
#   sudo ./install-ollama-model.sh --model gpt-oss:20b --from /path/to/indirilen-dosyalar
#   sudo ./install-ollama-model.sh --model nomic-embed-text --from ./ollama-gpt-oss-20b-v1
#
# Argümanlar:
#   --model <isim[:tag]>    Kurulacak modelin adı (zorunlu). Klasördeki dosya adını
#                            belirlemek İÇİN kullanılır: ollama-models-<isim>.tar.gz
#                            (":" "-" ile değiştirilir, ör. gpt-oss:20b -> gpt-oss-20b)
#   --from <dizin>          İndirilen ollama-models-*.tar.gz[.partNN] dosyalarının
#                            bulunduğu klasör (varsayılan: betiğin kendi dizini)
#   --install-dir <dizin>   Kurulum dizini, .env burada aranır (varsayılan: /data)
#   --set-default           Kurulumdan sonra .env'deki AGENT_MODEL'i bu modele çeker
#                            (mevcut sohbet modeli olarak varsayılan yapar)
#   --no-restart            Kurulumdan sonra ollama container'ını yeniden başlatma
#
# İdempotenttir: model manifest'i zaten diskteyse (aynı isim:tag) hiçbir şey
# yapmadan başarıyla çıkar — birden fazla kez güvenle çalıştırılabilir.
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

c_green() { printf '\033[0;32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[0;33m%s\033[0m\n' "$1"; }
c_red() { printf '\033[0;31m%s\033[0m\n' "$1"; }
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FROM_DIR="$SCRIPT_DIR"
INSTALL_DIR="/data"
MODEL=""
SET_DEFAULT=0
DO_RESTART=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --from) FROM_DIR="$(realpath -m "$2")"; shift 2 ;;
    --install-dir) INSTALL_DIR="$(realpath -m "$2")"; shift 2 ;;
    --set-default) SET_DEFAULT=1; shift ;;
    --no-restart) DO_RESTART=0; shift ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *) c_red "Bilinmeyen argüman: $1 (bkz. --help)"; exit 1 ;;
  esac
done

if [[ -z "$MODEL" ]]; then
  c_red "--model <isim[:tag]> zorunludur (ör. --model gpt-oss:20b)"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  c_red "Bu betik root olarak çalıştırılmalı: sudo ./install-ollama-model.sh ..."
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
MODELS_DIR="$DATA_DIR/ollama/models"

# "gpt-oss:20b" -> isim=gpt-oss, tag=20b ; "nomic-embed-text" -> isim=nomic-embed-text, tag=latest
MODEL_BASENAME="${MODEL%%:*}"
MODEL_TAG="latest"
[[ "$MODEL" == *:* ]] && MODEL_TAG="${MODEL#*:}"
# Dosya adı için ":" güvenli değil -> "-" kullanılır (export-ollama-embed-model.sh'in
# ürettiği paketlerle eşleşmesi için release/paket hazırlarken de aynı kural izlenmeli).
FILE_SLUG="$(echo "$MODEL" | tr ':' '-')"

echo
c_green "════════════════════════════════════════════════════════════════"
c_green " Ollama Model Kurulumu: ${MODEL}"
c_green "════════════════════════════════════════════════════════════════"
echo " Kaynak dosyalar : $FROM_DIR"
echo " Kurulum dizini  : $INSTALL_DIR"
echo " Models dizini   : $MODELS_DIR"
echo

# ── 1. İdempotency: model zaten kurulu mu? ───────────────────────────────
MANIFEST_PATH="$MODELS_DIR/manifests/registry.ollama.ai/library/${MODEL_BASENAME}/${MODEL_TAG}"
if [[ -f "$MANIFEST_PATH" ]]; then
  c_green "✓ ${MODEL} zaten diskte kurulu — indirme/açma atlandı: $MANIFEST_PATH"
  SKIP_EXTRACT=1
else
  SKIP_EXTRACT=0
fi

if [[ "$SKIP_EXTRACT" -eq 0 ]]; then
  step "Disk alanı kontrol ediliyor"
  df -h "$DATA_DIR" 2>/dev/null | tail -n +1 || true

  # ── 2. Kaynak dosyayı bul: tam dosya veya .part parçaları ────────────────
  MODEL_TAR=""
  CANDS=(
    "$FROM_DIR/ollama-models-${FILE_SLUG}.tar.gz"
    "$FROM_DIR/ollama-models-${MODEL_BASENAME}.tar.gz"
  )
  for c in "${CANDS[@]}"; do
    [[ -s "$c" ]] && { MODEL_TAR="$c"; break; }
  done

  TMP_MERGED=""
  if [[ -z "$MODEL_TAR" ]]; then
    # Parçalanmış dosya: ollama-models-<slug>.tar.gz.part01, part02, ...
    for base_slug in "$FILE_SLUG" "$MODEL_BASENAME"; do
      part1="$FROM_DIR/ollama-models-${base_slug}.tar.gz.part01"
      if [[ -s "$part1" ]]; then
        step "Parçalar birleştiriliyor (ollama-models-${base_slug}.tar.gz.part*)"
        parts_sha="$FROM_DIR/ollama-models-${base_slug}.tar.gz.parts.sha256"
        if [[ -s "$parts_sha" ]]; then
          (cd "$FROM_DIR" && sha256sum -c "$(basename "$parts_sha")") || {
            c_red "Parça bütünlük doğrulaması başarısız — dosyalar bozuk/eksik olabilir."; exit 1; }
          c_green "✓ Parça bütünlüğü doğrulandı."
        else
          c_yellow "⚠ Parça sha256 dosyası yok, bütünlük doğrulanamıyor: $parts_sha"
        fi
        TMP_MERGED="$(mktemp -d)/ollama-models-${base_slug}.tar.gz"
        cat "$FROM_DIR/ollama-models-${base_slug}.tar.gz.part"* > "$TMP_MERGED"
        MODEL_TAR="$TMP_MERGED"
        break
      fi
    done
  fi

  if [[ -z "$MODEL_TAR" ]]; then
    c_red "ollama-models-${FILE_SLUG}.tar.gz (veya .part parçaları) bulunamadı: $FROM_DIR"
    c_yellow "  Beklenen dosya adı: ollama-models-${FILE_SLUG}.tar.gz veya .part01/.part02/..."
    exit 1
  fi

  if [[ -z "$TMP_MERGED" && -s "${MODEL_TAR}.sha256" ]]; then
    (cd "$(dirname "$MODEL_TAR")" && sha256sum -c "$(basename "$MODEL_TAR").sha256") || {
      c_red "Bütünlük doğrulaması başarısız: $MODEL_TAR"; exit 1; }
    c_green "✓ Bütünlük doğrulandı: $(basename "$MODEL_TAR")"
  fi

  step "Model açılıyor: ${MODEL}"
  mkdir -p "$DATA_DIR/ollama"
  tar xzf "$MODEL_TAR" -C "$DATA_DIR/ollama"
  chmod -R 777 "$DATA_DIR/ollama" 2>/dev/null || true
  [[ -n "$TMP_MERGED" ]] && rm -rf "$(dirname "$TMP_MERGED")"

  if [[ -f "$MANIFEST_PATH" ]]; then
    c_green "✓ Model açıldı ve doğrulandı: $MANIFEST_PATH"
  else
    c_red "⚠ Açma tamamlandı ama beklenen manifest bulunamadı: $MANIFEST_PATH"
    c_yellow "  Model adı/tag'i yanlış olabilir, 'ollama list' ile kontrol edin."
  fi
fi

# ── 3. .env: opsiyonel varsayılan model ──────────────────────────────────
if [[ "$SET_DEFAULT" -eq 1 ]]; then
  step "AGENT_MODEL varsayılan modeli güncelleniyor: ${MODEL}"
  if grep -q '^AGENT_MODEL=' "$ENV_FILE"; then
    sed -i "s|^AGENT_MODEL=.*|AGENT_MODEL=${MODEL}|" "$ENV_FILE"
  else
    echo "AGENT_MODEL=${MODEL}" >> "$ENV_FILE"
  fi
  c_green "✓ .env içinde AGENT_MODEL=${MODEL} ayarlandı."
  c_yellow "  Not: arayüzden Ayarlar → AI Model ile de değiştirilmiş olabilir (DB önceliklidir)."
fi

# ── 4. Ollama'yı yeniden başlat (yeni model listesini garanti taze görsün) ─
if [[ "$DO_RESTART" -eq 1 ]]; then
  step "Ollama yeniden başlatılıyor"
  cd "$INSTALL_DIR"
  if docker compose -f "$COMPOSE_FILE" --profile ollama ps ollama 2>/dev/null | grep -q .; then
    docker compose -f "$COMPOSE_FILE" --profile ollama restart ollama || true
  else
    c_yellow "· ollama servisi çalışmıyor görünüyor, başlatılıyor..."
    docker compose -f "$COMPOSE_FILE" --profile ollama up -d --no-build ollama || true
  fi
fi

echo
c_green "════════════════════════════════════════════════════════════════"
c_green " Tamamlandı: ${MODEL}"
c_green "════════════════════════════════════════════════════════════════"
echo " Doğrulamak için:"
echo "   docker compose -f $COMPOSE_FILE --profile ollama exec ollama ollama list"
echo " AI Chat/Agent'ta kullanmak için Ayarlar → AI Model'den seçin"
echo " (veya --set-default ile .env'deki AGENT_MODEL'i bu modele çekin)."
