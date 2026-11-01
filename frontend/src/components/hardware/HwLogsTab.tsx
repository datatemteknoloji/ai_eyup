import React, { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import { EmptyState, Select } from '../aiops/ui'
import { Panel } from '../insights/insightsKit'

/**
 * Faz 3b — «Donanım Logları» sekmesi: ESXi (vCenter SEL/vmkernel), OLVM/OpenShift host'ları, tekil fizikseller
 * (Linux/Windows, portal, in-band ipmitool, BMC Redfish) ve şasi alarmları — host sınıfına göre.
 * Salt-okunur. Metinler sunucuda maskelenmiştir (IP/UUID/MAC/WWN). Kaynaklar varsayılan KAPALI; kapalı kaynak açıkça gösterilir.
 */
const HOST_CLASSES = ['esxi', 'ocp', 'olvm', 'hv_other', 'chassis', 'physical'] as const
const SOURCES = ['esxi_sel', 'esxi_vmkernel', 'linux_journal', 'windows_event', 'ipmi_sel', 'bmc_redfish', 'portal_alert'] as const

const SEV_CLS: Record<string, string> = {
  critical: 'bg-red-500/15 text-red-300 border-red-500/30',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  info: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
}

const fmt = (iso?: string | null): string => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return d.toDateString() === new Date().toDateString() ? hm : `${d.toLocaleDateString()} ${hm}`
}

export const HwLogsTab: React.FC = () => {
  const t = useT()
  const [hostClass, setHostClass] = useState('')
  const [source, setSource] = useState('')
  const [severity, setSeverity] = useState('')
  const [days, setDays] = useState('7')
  const q = useQuery<any>({
    queryKey: ['hw-log-overview', hostClass, source, severity, days],
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,      // filtre değişiminde kaynak/sınıf çipleri kaybolup yeniden çıkmasın
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hw/log-overview?host_class=${hostClass}&source=${source}&severity=${severity}&days=${days}&limit=300`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
  })
  const d = q.data
  const items: any[] = d?.items || []
  const byClass: Record<string, number> = d?.counts?.by_class || {}
  const classTotal = Object.values(byClass).reduce((a, b) => a + b, 0)
  const sources: any[] = d?.sources || []
  const runTxt = d?.last_run_at ? t('hwl_last_run', { t: fmt(d.last_run_at) }) : t('hwlog_never_run')

  return (
    <div data-testid="hw-logs-tab" className="space-y-3">
      <Panel>
        <div className="p-3 space-y-2">
          <div className="flex flex-wrap items-center gap-1.5" data-testid="hw-logs-sources">
            <span className="text-[10px] uppercase tracking-wide text-slate-500 mr-1">{t('hwl_sources')}</span>
            {sources.map(s => (
              <button key={s.key} type="button" data-testid={`hw-logs-src-${s.key}`} aria-pressed={source === s.key}
                onClick={() => setSource(source === s.key ? '' : s.key)}
                title={s.enabled ? t('hwl_src_on') : t('hwl_src_off')}
                className={`text-[11px] px-2 py-0.5 rounded-sm border transition-colors ${source === s.key ? 'bg-blue-600 border-blue-500 text-white' : s.enabled ? 'border-white/[0.12] text-slate-200 hover:bg-white/[0.05]' : 'border-white/[0.06] text-slate-500 hover:text-slate-300'}`}>
                {t(`hwlog_src_${s.key}` as any)}
                <span className="ml-1 opacity-70">{s.enabled ? `${s.entries}` : t('hwl_src_off')}</span>
              </button>
            ))}
          </div>
          <div className="text-[11px] text-slate-500 flex flex-wrap gap-x-3">
            <span>{runTxt}</span>
            {Number(d?.last_run_errors || 0) > 0 && <span className="text-amber-400">{t('hwlog_run_errors', { n: d.last_run_errors })}</span>}
          </div>
        </div>
      </Panel>

      <Panel>
        <div className="px-3 pt-3 flex gap-1.5 flex-wrap items-center" data-testid="hw-logs-class-chips" title={t('hw_class_hint')}>
          {[['', classTotal] as [string, number], ...HOST_CLASSES.filter(c => (byClass[c] ?? 0) > 0).map(c => [c, byClass[c]] as [string, number])].map(([c, n]) => (
            <button key={c || 'all'} type="button" data-testid={`hw-logs-class-${c || 'all'}`} aria-pressed={hostClass === c}
              onClick={() => setHostClass(c)}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${hostClass === c ? 'bg-blue-600 border-blue-500 text-white' : 'border-white/[0.1] text-slate-300 hover:text-white hover:bg-white/[0.05]'}`}>
              {c ? t(`hw_class_${c}` as any) : t('hw_filter_all')} <span className="opacity-70">{n}</span>
            </button>
          ))}
        </div>
        <div className="p-3 flex gap-2 flex-wrap items-center border-b border-white/[0.06]">
          <Select value={severity} onChange={setSeverity}>
            <option value="">{t('hwl_sev_default')}</option>
            <option value="critical">{t('hwlog_sev_critical')}</option>
            <option value="warning">{t('hwlog_sev_warning')}</option>
            <option value="all">{t('hwl_sev_all')}</option>
          </Select>
          <Select value={days} onChange={setDays}>
            {['1', '7', '14', '30'].map(n => <option key={n} value={n}>{t('hwlog_window', { n })}</option>)}
          </Select>
          {source && <button type="button" onClick={() => setSource('')} className="text-xs px-2 py-1 rounded-sm border border-white/[0.1] text-slate-300 hover:text-white">{t('hwlog_src_' + source as any)} ✕</button>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-slate-500">
                {['hwl_col_sev', 'hwl_col_host', 'hwl_col_source', 'hwl_col_cat', 'hwl_col_msg', 'hwl_col_last'].map(k => <th key={k} className="px-3 py-2 font-medium">{t(k as any)}</th>)}
              </tr>
            </thead>
            <tbody>
              {items.map((it: any) => (
                <tr key={it.id} data-testid="hw-logs-row" className="border-t border-white/[0.05] align-top">
                  <td className="px-3 py-2"><span className={`text-[11px] px-1.5 py-0.5 rounded-sm border ${SEV_CLS[it.severity] || SEV_CLS.info}`}>{t(`hwlog_sev_${it.severity}` as any)}</span></td>
                  <td className="px-3 py-2 text-xs text-slate-100">
                    {it.target?.name || '—'}
                    <span data-testid="hw-logs-class-tag" className="ml-2 text-[10px] text-slate-400 border border-white/10 rounded-sm px-1 align-middle">{t(`hw_class_${it.host_class}` as any)}</span>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-300 whitespace-nowrap">{t(`hwlog_src_${it.source}` as any)}</td>
                  <td className="px-3 py-2 text-xs text-slate-300">{it.category ? t(`hwlog_cat_${it.category}` as any) : '—'}</td>
                  <td className="px-3 py-2 text-xs text-slate-200 wrap-break-word max-w-xl" title={it.message}>{it.message}</td>
                  <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">{it.occurrences > 1 ? `${it.occurrences}× · ` : ''}{fmt(it.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!q.isLoading && items.length === 0 && (
            d && !sources.some(s => s.key !== 'portal_alert' && s.enabled)
              ? (
                <div data-testid="hw-logs-disabled" className="p-4 text-xs text-slate-400 space-y-1">
                  <div>{t('hwl_disabled')}</div>
                  <div className="text-slate-500">{t('hwl_empty')}</div>
                  <Link to="/settings" className="text-blue-300 hover:text-blue-200">{t('hwl_disabled_link')}</Link>
                </div>
              )
              : <div data-testid="hw-logs-empty"><EmptyState text={t('hwl_empty')} /></div>
          )}
        </div>
        {d?.note && <div className="px-4 py-2 text-[11px] text-slate-500 border-t border-white/[0.06]">{d.note}</div>}
      </Panel>
    </div>
  )
}

export default HwLogsTab
export { SOURCES as HW_LOG_SOURCES }
