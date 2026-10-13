/** Monitoring / sohbet grafik zamanı — tarayıcı TZ ile gösterim; API UTC.

Kalıcı kural:
- Unix saniye (< 1e12) veya ms
- ISO: offset/Z yoksa UTC kabul et (naive UTC sızıntısına karşı)
- Biçim: Intl → kullanıcının tarayıcı dil/saat dilimi (sabit +3 yok)
*/

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export function parseApiTime(v: string | number | Date | null | undefined): Date | null {
  if (v == null || v === '') return null
  if (v instanceof Date) return Number.isNaN(v.getTime()) ? null : v
  if (typeof v === 'number' && Number.isFinite(v)) {
    const ms = v < 1e12 ? v * 1000 : v
    const d = new Date(ms)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const s = String(v).trim()
  if (!s) return null
  // Saf sayısal string (unix)
  if (/^\d+(\.\d+)?$/.test(s)) {
    const n = Number(s)
    return parseApiTime(n)
  }
  // Offset/Z yoksa UTC say (PG/naive sızıntısı)
  let iso = s
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) {
    iso = s.includes('T') ? `${s}Z` : `${s.replace(' ', 'T')}Z`
  }
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

function localeTag(locale?: string): string | undefined {
  return locale || undefined
}

/** Eksen etiketi (kısa saat veya gün+saat). */
export function formatChartTick(
  v: string | number | Date | null | undefined,
  spanMs?: number,
  locale?: string,
): string {
  const d = parseApiTime(v)
  if (!d) return ''
  const loc = localeTag(locale)
  const span = spanMs ?? 0
  if (span > 2 * 24 * 3600_000) {
    return d.toLocaleString(loc, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  }
  if (span > 24 * 3600_000) {
    return d.toLocaleString(loc, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleTimeString(loc, { hour: '2-digit', minute: '2-digit' })
}

/** Tooltip / as_of / last_sample. */
export function formatChartLabel(
  v: string | number | Date | null | undefined,
  locale?: string,
): string {
  const d = parseApiTime(v)
  if (!d) return '—'
  return d.toLocaleString(localeTag(locale), {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

export function formatDateTime(
  v: string | number | Date | null | undefined,
  locale?: string,
): string {
  return formatChartLabel(v, locale)
}
