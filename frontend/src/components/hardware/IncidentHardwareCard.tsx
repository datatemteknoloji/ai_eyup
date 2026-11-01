import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Cpu } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import { useCapabilities } from '../../hooks/useCapabilities'
import { DemoStrip, HealthBadge } from './hwUi'

/**
 * Incident detayında «İlgili donanım»: incident'ın donanım olayları ve etkilenen sunucularının donanım sağlığı.
 * Özet bilgidir (BMC adresi / seri / konsol YOK). Donanım entegrasyonu yoksa ya da ilgili kayıt yoksa hiç render edilmez.
 */
export const IncidentHardwareCard: React.FC<{ incidentId: number }> = ({ incidentId }) => {
  const t = useT()
  const { hasHw } = useCapabilities()
  const q = useQuery<any>({
    queryKey: ['incident-hw', incidentId],
    enabled: hasHw && !!incidentId,
    retry: false,
    staleTime: 30_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/incidents/${incidentId}/hardware`)
      if (!r.ok) return { items: [] }
      return r.json()
    },
  })
  const items: any[] = q.data?.items ?? []
  if (!hasHw || !q.data?.enabled || items.length === 0) return null
  return (
    <div data-testid="incident-hw-card" className="rounded-lg border border-white/[0.08] bg-slate-900/40 p-3 space-y-2">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-300"><Cpu size={13} /> {t('hw_inc_title')}</div>
      {q.data.demo && <DemoStrip />}
      {items.map((it: any) => (
        <div key={it.hw_server_id} className="space-y-1.5 border-t border-white/[0.05] pt-2 first:border-0 first:pt-0">
          <div className="flex items-center gap-2 flex-wrap text-sm text-slate-100">
            <span>{it.name}</span>
            <HealthBadge health={it.health} />
            <span className="text-xs text-slate-500">{[it.vendor?.toUpperCase(), it.model, it.enclosure].filter(Boolean).join(' · ')}</span>
            {it.connected === false && <span className="text-xs text-red-300">{t('hw_inc_unreachable')}</span>}
          </div>
          {(it.alerts || []).slice(0, 3).map((a: any, i: number) => (
            <div key={i} className="text-xs text-slate-300 flex gap-2">
              <span className={a.severity === 'critical' ? 'text-red-300' : 'text-amber-300'}>{a.severity}</span>
              <span className="truncate" title={a.message}>{a.message}</span>
            </div>
          ))}
          {it.impact && (it.impact.vm_count > 0 || it.impact.cluster) && (
            <div className="rounded-sm border border-amber-500/20 bg-amber-500/5 px-2 py-1.5 text-xs text-amber-100 space-y-0.5" data-testid="hw-impact">
              <div className="font-medium">{t('hw_impact_title')}</div>
              {it.impact.vm_count > 0 && (
                <div>{t('hw_impact_vms', { n: it.impact.vm_count, on: it.impact.vm_powered_on })}</div>
              )}
              {(it.impact.services || []).length > 0 && (
                <div>{t('hw_impact_services')}: {(it.impact.services as any[]).map(s => `${s.name} (${s.tier})`).join(', ')}</div>
              )}
              {it.impact.cluster && (
                <div className={it.impact.cluster.ha_risk ? 'text-red-300' : ''}>
                  {t('hw_impact_cluster', { c: it.impact.cluster.name, n: it.impact.cluster.healthy_hosts, m: it.impact.cluster.hosts })}
                  {it.impact.cluster.ha_risk ? ` — ${t('hw_impact_ha_risk')}` : ''}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default IncidentHardwareCard
