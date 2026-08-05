#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Tek bir Ollama modelini (blobs + manifest) dışa aktarır — genelde RAG
# embedding modeli (nomic-embed-text) için kullanılır, ama herhangi bir chat
# modeli (ör. "gpt-oss:20b") için de çalışır — dist "with-ollama" paketi ve
# ayrı chat-model runtime release'leri için.
#
# Kullanım:
#   ./scripts/export-ollama-embed-model.sh [çıktı.tar.gz] [ollama-models-dir] [model[:tag]]
#
# "model:tag" biçiminde tag verilmezse "latest" (yoksa dizindeki ilk tag)
# kullanılır. Birden fazla tag'i olan modellerde (ör. "gpt-oss" -> 20b/120b)
# YANLIŞ tag'in paketlenmemesi için tag'i EXPLICIT vermeniz önerilir.
#
# Varsayılanlar:
#   çıktı  : ollama-models-nomic-embed-text.tar.gz
#   models : /usr/share/ollama/.ollama/models  (host ollama) veya
#            /data/data/ollama/models
#   model  : nomic-embed-text
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

OUT_FILE="${1:-ollama-models-nomic-embed-text.tar.gz}"
MODEL_NAME="${3:-nomic-embed-text}"

find_models_dir() {
  local candidates=(
    "${2:-}"
    "/usr/share/ollama/.ollama/models"
    "${HOME}/.ollama/models"
    "/data/data/ollama/models"
    "/data/data/ollama"
  )
  local d
  for d in "${candidates[@]}"; do
    [[ -z "$d" ]] && continue
    if [[ -d "$d/manifests" || -d "$d/blobs" ]]; then
      echo "$d"
      return 0
    fi
    # volume kökü: .../ollama (içinde models yok, blobs doğrudan)
    if [[ -d "$d/models/manifests" ]]; then
      echo "$d/models"
      return 0
    fi
  done
  return 1
}

MODELS_DIR="$(find_models_dir "${2:-}" || true)"
if [[ -z "${MODELS_DIR:-}" ]]; then
  echo "✗ Ollama models dizini bulunamadı." >&2
  echo "  Önce: ollama pull ${MODEL_NAME}" >&2
  exit 1
fi

# "gpt-oss:20b" gibi isim:tag biçimini ayır — ayrılmamış bırakılırsa (ör. "nomic-embed-text")
# ollama manifest dizin yapısı zaten tag'i ayrı bir alt dizin olarak tutuyor (bkz. aşağıdaki
# "latest" / ls-ile-ilk-bulunan fallback). İsim:tag ayrılmadan aynı ad altında birden fazla
# tag varsa (örn. "gpt-oss" -> 20b VE 120b) yanlış (alfabetik ilk) tag'in paketlenmesi riski
# vardı — bu artık isim:tag açıkça verildiğinde engelleniyor.
MODEL_BASENAME="${MODEL_NAME%%:*}"
MODEL_TAG_ARG=""
[[ "$MODEL_NAME" == *:* ]] && MODEL_TAG_ARG="${MODEL_NAME#*:}"

MANIFEST_DIR="${MODELS_DIR}/manifests/registry.ollama.ai/library/${MODEL_BASENAME}"
if [[ ! -d "$MANIFEST_DIR" ]]; then
  # HF tarzı path yoksa library altında ara
  MANIFEST_DIR="$(find "${MODELS_DIR}/manifests" -type d -name "${MODEL_BASENAME}" 2>/dev/null | head -1 || true)"
fi
if [[ -z "${MANIFEST_DIR:-}" || ! -d "$MANIFEST_DIR" ]]; then
  echo "✗ Model manifest bulunamadı: ${MODEL_NAME}" >&2
  echo "  Models dir: ${MODELS_DIR}" >&2
  echo "  Önce: ollama pull ${MODEL_NAME}" >&2
  exit 1
fi

MANIFEST_FILE=""
if [[ -n "$MODEL_TAG_ARG" ]]; then
  if [[ -f "${MANIFEST_DIR}/${MODEL_TAG_ARG}" ]]; then
    MANIFEST_FILE="${MANIFEST_DIR}/${MODEL_TAG_ARG}"
  else
    echo "✗ Tag bulunamadı: ${MODEL_TAG_ARG} (dizin: $MANIFEST_DIR)" >&2
    echo "  Mevcut tag'ler: $(ls "$MANIFEST_DIR" 2>/dev/null | tr '\n' ' ')" >&2
    exit 1
  fi
else
  for tag in latest "$(ls "$MANIFEST_DIR" 2>/dev/null | head -1)"; do
    [[ -f "${MANIFEST_DIR}/${tag}" ]] && { MANIFEST_FILE="${MANIFEST_DIR}/${tag}"; break; }
  done
fi
if [[ -z "$MANIFEST_FILE" ]]; then
  echo "✗ Manifest dosyası yok: $MANIFEST_DIR" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

python3 - "$MANIFEST_FILE" "$MODELS_DIR" "$TMP" "$MODEL_NAME" <<'PY'
import json, os, shutil, sys
manifest_path, models_dir, tmp, model_name = sys.argv[1:5]
with open(manifest_path) as f:
    m = json.load(f)
digests = set()
cfg = (m.get("config") or {}).get("digest") or ""
if cfg.startswith("sha256:"):
    digests.add(cfg[7:])
for layer in m.get("layers") or []:
    d = layer.get("digest") or ""
    if d.startswith("sha256:"):
        digests.add(d[7:])
blobs_src = os.path.join(models_dir, "blobs")
blobs_dst = os.path.join(tmp, "blobs")
os.makedirs(blobs_dst, exist_ok=True)
total = 0
for dig in digests:
    name = f"sha256-{dig}"
    src = os.path.join(blobs_src, name)
    if not os.path.isfile(src):
        raise SystemExit(f"Eksik blob: {src}")
    shutil.copy2(src, os.path.join(blobs_dst, name))
    total += os.path.getsize(src)
# manifest path mirror (registry.ollama.ai/library/<model>/<tag>)
rel = os.path.relpath(manifest_path, os.path.join(models_dir, "manifests"))
dst_m = os.path.join(tmp, "manifests", rel)
os.makedirs(os.path.dirname(dst_m), exist_ok=True)
shutil.copy2(manifest_path, dst_m)
print(f"model={model_name} blobs={len(digests)} size_mb={total/1024/1024:.1f}")
PY

# Tarball kökü: models/{blobs,manifests}
# docker volume: ${DATA_DIR}/ollama:/root/.ollama → /root/.ollama/models/...
mkdir -p "${TMP}/pack/models"
mv "${TMP}/blobs" "${TMP}/pack/models/blobs"
mv "${TMP}/manifests" "${TMP}/pack/models/manifests"

echo "▶ Kaynak  : ${MODELS_DIR}"
echo "▶ Model   : ${MODEL_NAME}"
echo "▶ Çıktı   : ${OUT_FILE}"
tar czf "$OUT_FILE" -C "${TMP}/pack" .
# .sha256 dosyasına DAİMA sadece dosya adı (relative) yazılır — OUT_FILE mutlak
# bir yol olarak verilirse (ör. "/tmp/x/model.tar.gz") "sha256sum $OUT_FILE" bu
# mutlak yolu dosyaya gömer ve "sha256sum -c" başka bir dizinde/makinede
# (ör. kurulum yapılan müşteri sunucusunda) "No such file or directory" ile
# başarısız olur. cd + basename ile bu her zaman taşınabilir kalır.
(cd "$(dirname "$OUT_FILE")" && sha256sum "$(basename "$OUT_FILE")" > "$(basename "$OUT_FILE").sha256")
du -sh "$OUT_FILE"
echo "✔ Hazır: $OUT_FILE"
