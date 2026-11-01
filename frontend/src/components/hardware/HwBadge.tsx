import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Cpu } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import { useCapabilities } from '../../hooks/useCapabilities'

type HwItem = { health: string; connected?: boolean | null; critical_alerts?: number; warranty_expired?: boolean | null; warranty_days?: number | null }

/** Liste sayfaları için tek istekle tüm eşleşmiş hedeflerin donanım sağlığı (react-query aynı anahtarı paylaşır). */
export function useHwHealthMap(kind: 'server' | 'esxi') {
  const { hasHw } = useCapabilities()
  const q = useQuery<{ items: Record<string, HwItem> }>({
    queryKey: ['hw-health', kind],
    enabled: hasHw,
    retry: false,
    staleTime: 60_000,
    refetchInterval: 120_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hw/targets-health?kind=${kind}`)
      if (!r.ok) return { items: {} }
      return r.json()
    },
  })
  return q.data?.items ?? {}
}

/**
 * Linux/Windows liste satırı ve ESXi host kartı için küçük donanım rozeti.
 * Yalnız SORUN varken görünür (kritik/uyarı, bağlantısız, aktif kritik alarm, garanti bitti) — sağlıklı sunucuda gürültü yok.
 * Entegrasyon yoksa / eşleşme yoksa / yetki yoksa hiç render edilmez.
 */
export const HwBadge: React.FC<{ kind: 'server' | 'esxi'; id?: number | null }> = ({ kind, id }) => {
  const t = useT()
  const map = useHwHealthMap(kind)
  const it = id != null ? map[String(id)] : undefined
  if (!it) return null
  const bad = it.health === 'critical' || it.health === 'warning' || it.connected === false || (it.critical_alerts ?? 0) > 0
  const warrantyOnly = !bad && it.warranty_expired === true
  if (!bad && !warrantyOnly) return null
  const crit = it.health === 'critical' || (it.critical_alerts ?? 0) > 0
  const cls = crit ? 'bg-red-500/15 text-red-300 border-red-500/30' : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
  const label = warrantyOnly ? t('hw_badge_warranty') : crit ? t('hw_badge_critical') : t('hw_badge_warning')
  const title = [
    t('hw_badge_title'),
    it.health ? t(`hw_health_${['ok', 'warning', 'critical'].includes(it.health) ? it.health : 'unknown'}` as any) : '',
    (it.critical_alerts ?? 0) > 0 ? t('hw_badge_alerts', { n: it.critical_alerts ?? 0 }) : '',
    it.warranty_expired ? t('hw_warranty_expired') : '',
  ].filter(Boolean).join(' · ')
  return (
    <span data-testid="hw-badge" title={title}
      className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-sm border font-medium ${cls}`}>
      <Cpu size={10} /> {label}
    </span>
  )
}

export default HwBadge
