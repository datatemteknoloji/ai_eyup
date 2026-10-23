import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import { useCapabilities } from '../../hooks/useCapabilities'
import { DemoStrip, HealthBadge, WarrantyText, formFactorLabel, val } from './hwUi'

/**
 * Linux/Windows çekmecesi ve host paneli için "Donanım" kartı.
 * - Entegrasyon yoksa / eşleşme yoksa / kullanıcının `hardware` modülü yoksa (403) HİÇ render edilmez.
 * - Konsol/güç/uzaktan erişim düğmesi YOK; yalnız yönetim konsoluna (OME/OneView) bağlantı.
 */
export const HwServerCard: React.FC<{ kind: 'server' | 'esxi'; id: number }> = ({ kind, id }) => {
  const t = useT()
  const { hasHw } = useCapabilities()
  const q = useQuery<any>({
    queryKey: ['hw-by-target', kind, id],
    enabled: hasHw && !!id,
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hw/servers/by-target?kind=${kind}&id=${id}`)
      if (!r.ok) return { available: false }
      return r.json()
    },
  })
  const s = q.data?.server
  if (!hasHw || !q.data?.available || !s) return null
  return (
    <div data-testid="hw-server-card" className="bg-cyber-card/50 rounded-xl border border-white/[0.06] p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-white">{t('hw_card_title')}</h3>
        <div className="flex items-center gap-2">
          {q.data.demo && <span className="text-[11px] px-1.5 rounded bg-fuchsia-500/20 text-fuchsia-300">DEMO</span>}
          <HealthBadge health={s.health} />
        </div>
      </div>
      {q.data.demo && <DemoStrip />}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        {([
          [t('hw_col_bmc'), val(s.bmc_ip, t) + (s.bmc_type ? ` (${s.bmc_type})` : '')],
          [t('hw_col_bmc_ver'), val(s.bmc_version, t)],
          [t('hw_col_model'), val(s.model, t)],
          [t('hw_col_serial'), val(s.serial, t)],
          [t('hw_col_form'), formFactorLabel(t, s.form_factor)],
          [t('hw_col_enclosure'), s.enclosure_name ? `${s.enclosure_name}${s.bay ? ' / ' + s.bay : ''}` : t('hw_not_measured')],
        ] as [string, string][]).map(([k, v]) => (
          <div key={k}>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div>
            <div className="text-slate-100 break-all">{v}</div>
          </div>
        ))}
        <div className="col-span-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">{t('hw_col_warranty')}</div>
          <div className="text-slate-100"><WarrantyText w={s.warranty} /></div>
        </div>
      </div>
      {(s.recent_alerts || []).length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">{t('hw_recent_alerts')}</div>
          {s.recent_alerts.slice(0, 3).map((a: any, i: number) => (
            <div key={i} className="text-xs text-slate-300 flex gap-2">
              <span className={a.severity === 'critical' ? 'text-red-300' : 'text-amber-300'}>{a.severity}</span>
              <span className="truncate" title={a.message}>{a.message}</span>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between text-[11px] text-slate-500">
        <span>{s.manager?.name ? `${s.manager.name}${s.manager.version ? ' ' + s.manager.version : ''} · ` : ''}{s.collected_at ? t('hw_updated', { d: new Date(s.collected_at).toLocaleString() }) : ''}</span>
        {s.web_url && !q.data.demo && (
          <a href={s.web_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-blue-300 hover:text-blue-200">
            {t('hw_open_console')} <ExternalLink size={11} />
          </a>
        )}
      </div>
    </div>
  )
}

export default HwServerCard
