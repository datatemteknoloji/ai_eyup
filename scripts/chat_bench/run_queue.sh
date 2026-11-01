#!/usr/bin/env bash
# Tam bench kuyruğu (sıralı; nohup ile başlatın):
#   nohup scripts/chat_bench/run_queue.sh > /tmp/chat-bench/queue.log 2>&1 &
# Argümanlar (isteğe bağlı): tur etiketleri. Varsayılan: step5-full-r1 step5-full-r2 step5-full-r3
# Kural: 3. ve sonraki tur, başlangıcı sabah 07:00–20:00 arasına düşecekse ATLANIR
#        (<etiket>.SKIPPED işareti yazılır; rapor «zaman yetmedi» der).
# Bittiğinde TEK RAPOR otomatik üretilir (report_overnight.py).
cd "$(dirname "$0")/../.." || exit 1
OUT=/tmp/chat-bench
mkdir -p "$OUT"
if [ "$#" -gt 0 ]; then LABELS=("$@"); else LABELS=(step5-full-r1 step5-full-r2 step5-full-r3); fi
i=0
for L in "${LABELS[@]}"; do
  i=$((i+1))
  H=$((10#$(date +%H)))
  if [ "$i" -ge 3 ] && [ "$H" -ge 7 ] && [ "$H" -lt 20 ]; then
    echo "$L: zaman yetmedi (tur başlangıcı $(date +%H:%M), 07:00'den sonra)" | tee "$OUT/$L.SKIPPED"
    continue
  fi
  echo "[$(date +%F\ %T)] $L başlıyor"
  date +%s > "$OUT/$L.start"
  python3 scripts/chat_bench/run.py --module all --set all --tag "$L" --trace > "$OUT/$L.log" 2>&1
  echo "[$(date +%F\ %T)] $L bitti (çıkış $?)"
done
LJ=$(IFS=,; echo "${LABELS[*]}")
python3 scripts/chat_bench/report_overnight.py --labels "$LJ" --part step5-part --baselines step3-full,step4-part \
  --date "$(date +%Y%m%d)" >> "$OUT/queue.log" 2>&1
echo "[$(date +%F\ %T)] kuyruk bitti; rapor üretildi"
