/** Host kartı / grafik başlığı: hostname (kısa ad) öncelikli, IP ikincil. */

function looksLikeIp(raw: string): boolean {
  const s = raw.trim()
  if (!s) return false
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(s)) return true
  if (s.includes(':') && !s.includes(' ')) return true
  return false
}

function shortHostname(raw: string): string {
  const s = raw.trim()
  if (!s || looksLikeIp(s)) return s
  return s.split('.')[0] || s
}

export type VirtHostNameFields = {
  host_name?: string | null
  display_name?: string | null
  ip_address?: string | null
}

export function virtHostTitle(host: VirtHostNameFields): string {
  const candidates = [host.display_name, host.host_name].filter(
    (v): v is string => Boolean(v && String(v).trim()),
  )
  for (const c of candidates) {
    if (!looksLikeIp(c)) return shortHostname(c)
  }
  return shortHostname(host.display_name || host.host_name || host.ip_address || '') || '—'
}

export function virtHostIpHint(host: VirtHostNameFields): string | null {
  const title = virtHostTitle(host)
  const ip = (host.ip_address || '').trim()
  if (ip && ip !== title && looksLikeIp(ip)) return ip
  const hn = (host.host_name || '').trim()
  if (hn && looksLikeIp(hn) && hn !== title) return hn
  return null
}
