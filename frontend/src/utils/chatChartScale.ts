/** Düşük aralıklı % serilerinde 0–100 sabiti dalgaları okunmaz kılar — veriye göre zoom. */
export function niceYDomain(minV: number, maxV: number, unit: string): { min: number; max: number } {
  if (!Number.isFinite(minV) || !Number.isFinite(maxV)) {
    return { min: 0, max: unit === '%' ? 100 : 1 }
  }
  if (maxV === minV) {
    if (unit === '%') {
      const mid = Math.min(100, Math.max(0, minV))
      return { min: Math.max(0, mid - 2), max: Math.min(100, mid + 2) }
    }
    return { min: minV - 1, max: maxV + 1 }
  }
  if (unit === '%') {
    const dataMin = Math.max(0, Math.min(minV, maxV))
    const dataMax = Math.min(100, Math.max(minV, maxV))
    const span = Math.max(0.5, dataMax - dataMin)
    // Geniş kullanım → tam 0–100; dar bant → zoom
    if (dataMax >= 75 || span >= 45) {
      return { min: 0, max: 100 }
    }
    let lo = dataMin <= 8 ? 0 : Math.max(0, dataMin - span * 0.2)
    let hi = Math.min(100, dataMax + Math.max(span * 0.25, 3))
    const step = hi - lo <= 20 ? 2 : 5
    lo = Math.floor(lo / step) * step
    hi = Math.ceil(hi / step) * step
    if (hi <= lo) hi = lo + step
    return { min: Math.max(0, lo), max: Math.min(100, hi) }
  }
  const pad = (maxV - minV) * 0.12 || 1
  return { min: minV - pad, max: maxV + pad }
}

/** Zaman ekseni tick aralığı — 12 saatte ~1 saat, uzun pencerede seyrelir. */
export function timeTickStepMs(spanMs: number): number {
  const h = 3600_000
  const d = 24 * h
  if (spanMs <= 2 * h) return 10 * 60_000
  if (spanMs <= 6 * h) return 30 * 60_000
  if (spanMs <= 16 * h) return h
  if (spanMs <= 36 * h) return 2 * h
  if (spanMs <= 4 * d) return 6 * h
  if (spanMs <= 14 * d) return d
  if (spanMs <= 60 * d) return 7 * d
  return 30 * d
}

/** Başlangıç/bitiş + aradaki yuvarlak saatler. Kenara çok yakın olanlar atlanır. */
export function niceTimeTicks(firstMs: number, lastMs: number): number[] {
  if (!Number.isFinite(firstMs) || !Number.isFinite(lastMs) || lastMs <= firstMs) {
    return Number.isFinite(firstMs) ? [firstMs] : []
  }
  const step = timeTickStepMs(lastMs - firstMs)
  const guard = step * 0.4
  const ticks = new Set<number>([firstMs, lastMs])
  let t = Math.ceil(firstMs / step) * step
  for (; t < lastMs; t += step) {
    if (t - firstMs < guard || lastMs - t < guard) continue
    ticks.add(t)
  }
  return [...ticks].sort((a, b) => a - b)
}
