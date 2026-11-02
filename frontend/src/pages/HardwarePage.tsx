import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronRight, ExternalLink, Server } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'
import { useCapabilities } from '../hooks/useCapabilities'
import { EmptyState, Kpi, NEON, PageHeader, SearchInput, Select, Tabs } from '../components/aiops/ui'
import { Panel } from '../components/insights/insightsKit'
import { HwLogsTab } from '../components/hardware/HwLogsTab'
import { HwBmcTab } from '../components/hardware/HwBmcTab'
import HwHostLogsCard from '../components/hardware/HwHostLogsCard'
import { FwStatusPanel, HwFirmwareTab } from '../components/hardware/HwFirmwareTab'
import type { BayCell, FwRow } from '../components/hardware/hwUi'
import { DemoStrip, HealthBadge, VendorLogo, WarrantyText, formFactorLabel, layoutBays, splitFirmware, val } from '../components/hardware/hwUi'

async function get(path: string) {
  const r = await fetch(`${API_BASE_URL}/hw${path}`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

async function send(path: string, method: 'POST' | 'DELETE', body?: unknown) {
  const r = await fetch(`${API_BASE_URL}/hw${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : `HTTP ${r.status}`)
  return j
}

/** Sunucu tablosu sütunu → API `sort_by` (beyaz liste; sıralama sunucuda TÜM kayıtlar üzerinde yapılır). */
const SORT_COLS: Array<[string, string]> = [
  ['hw_col_name', 'name'], ['hw_col_vendor', 'vendor'], ['hw_col_model', 'model'], ['hw_col_serial', 'serial'],
  ['hw_col_bmc', 'bmc_ip'], ['hw_col_bmc_ver', 'bmc_version'], ['hw_col_bios', 'bios_version'], ['hw_col_health', 'health'], ['hw_col_enclosure', 'enclosure'],
  ['hw_col_warranty', 'warranty'], ['hw_col_match', 'match'],
]
type SortDir = 'asc' | 'desc'

// Host sınıfı (sunucu tarafında hesaplanır; her kayıt tek sınıf). Sıra = chip sırası.
const HOST_CLASSES = ['esxi', 'ocp', 'olvm', 'hv_other', 'chassis', 'physical'] as const

type Tab = 'servers' | 'enclosures' | 'alerts' | 'logs' | 'bmc' | 'warranty' | 'unmatched' | 'firmware' | 'findings'

const Cell: React.FC<{ k: string; v: React.ReactNode }> = ({ k, v }) => (
  <div>
    <div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div>
    <div className="text-xs text-slate-100 break-all">{v}</div>
  </div>
)

const BayBox: React.FC<{ cell: BayCell }> = ({ cell }) => {
  const t = useT()
  if (cell.empty) {
    return (
      <div data-testid="hw-bay-empty" title={t('hw_encl_no_server_record_hint')} className="rounded-sm border border-dashed border-white/[0.08] p-2 text-xs">
        <span className="text-slate-500">#{cell.bay}</span>
        <div className="text-slate-600 mt-1">{t('hw_encl_no_server_record')}</div>
      </div>
    )
  }
  const shared = cell.servers.length > 1
  return (
    <div data-testid="hw-bay" data-shared={shared ? 'true' : 'false'} className="rounded-sm border border-white/[0.08] p-2 text-xs space-y-1.5">
      <div className="flex items-center justify-between gap-1">
        <span className="text-slate-400">#{cell.bay ?? '—'}</span>
        {shared ? <span className="text-[10px] text-slate-400" title={t('hw_encl_shared_bay', { n: cell.servers.length })}>×{cell.servers.length}</span> : <HealthBadge health={cell.servers[0].health} />}
      </div>
      {cell.servers.map(s => (
        <div key={s.id}>
          {shared && <div className="flex justify-end"><HealthBadge health={s.health} /></div>}
          <div className="text-slate-100 truncate" title={s.name}>{s.name}</div>
          <div className="text-slate-500 truncate">{val(s.model, t)}</div>
        </div>
      ))}
    </div>
  )
}

const FwTable: React.FC<{ rows: FwRow[]; dim?: boolean }> = ({ rows, dim }) => {
  const t = useT()
  return (
    <table className={`w-full text-xs ${dim ? 'text-slate-500' : 'text-slate-300'}`}>
      <thead><tr className="text-left text-[10px] uppercase tracking-wide text-slate-500">
        <th className="py-1 pr-3 font-medium">{t('hw_fw_col_type')}</th><th className="py-1 pr-3 font-medium">{t('hw_fw_col_name')}</th><th className="py-1 font-medium">{t('hw_fw_col_version')}</th>
      </tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.component_id ?? r.name}-${i}`} className="border-t border-white/[0.04]" data-testid="hw-fw-row">
            <td className="py-1 pr-3">{r.type || '—'}</td><td className="py-1 pr-3 break-all">{r.name || '—'}{r.location ? <span className="text-slate-500"> · {r.location}</span> : null}</td><td className="py-1 font-mono">{r.version || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const FirmwareSection: React.FC<{ rows: FwRow[]; readAt?: string | null }> = ({ rows, readAt }) => {
  const t = useT()
  if (!rows.length) return <div className="text-xs text-slate-500" data-testid="hw-fw-none">{t('hw_fw_none')}</div>
  const { installed, previous } = splitFirmware(rows)
  return (
    <details className="rounded-sm border border-white/[0.08] px-3 py-2" data-testid="hw-fw">
      <summary className="cursor-pointer text-xs text-slate-200">
        {t('hw_fw_title', { n: installed.length })}
        {readAt ? <span className="ml-2 text-[10px] text-slate-500">{t('hw_fw_read_at', { t: new Date(readAt).toLocaleString() })}</span> : null}
      </summary>
      <div className="mt-2 space-y-3">
        {installed.length > 0 && <FwTable rows={installed} />}
        {previous.length > 0 && (
          <details>
            <summary className="cursor-pointer text-[11px] text-slate-500">{t('hw_fw_prev')} ({previous.length})</summary>
            <div className="mt-1"><FwTable rows={previous} dim /></div>
          </details>
        )}
      </div>
    </details>
  )
}

const ServerRow: React.FC<{ s: any }> = ({ s }) => {
  const t = useT()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const unlink = useMutation({
    mutationFn: () => send(`/links/${s.id}`, 'DELETE'),
    onSuccess: () => { ['hw-servers', 'hw-unmatched', 'hw-summary', 'hw-server', 'hw-health'].forEach(k => qc.invalidateQueries({ queryKey: [k] })) },
  })
  const detail = useQuery<any>({ queryKey: ['hw-server', s.id], enabled: open, queryFn: () => get(`/servers/${s.id}`) })
  const d = detail.data?.server
  return (
    <>
      <tr className="border-t border-white/[0.05] hover:bg-white/[0.03] cursor-pointer" onClick={() => setOpen(!open)} data-testid="hw-row">
        <td className="px-3 py-2">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
        <td className="px-3 py-2 text-sm text-white">
          <span className="inline-flex items-center gap-2">
            <VendorLogo vendor={s.vendor} />
            {s.name}
          </span>
          {s.host_class ? <span data-testid="hw-class-tag" className="ml-2 text-[10px] text-slate-400 border border-white/10 rounded-sm px-1 align-middle">{t(`hw_class_${s.host_class}` as any)}</span> : null}
        </td>
        <td className="px-3 py-2 text-xs text-slate-300 uppercase">{s.vendor}</td>
        <td className="px-3 py-2 text-xs text-slate-300">{val(s.model, t)}</td>
        <td className="px-3 py-2 text-xs text-slate-300">{val(s.serial, t)}</td>
        <td className="px-3 py-2 text-xs text-slate-300">{val(s.bmc_ip, t)}</td>
        <td className="px-3 py-2 text-xs text-slate-300 font-mono" data-testid="hw-col-bmc-ver">{val(s.bmc_version, t)}</td>
        <td className="px-3 py-2 text-xs text-slate-300 font-mono" data-testid="hw-col-bios">{val(s.bios_version, t)}</td>
        <td className="px-3 py-2"><HealthBadge health={s.health} /></td>
        <td className="px-3 py-2 text-xs text-slate-300">{s.enclosure_name ? `${s.enclosure_name}${s.bay ? ' / ' + s.bay : ''}` : formFactorLabel(t, s.form_factor)}</td>
        <td className="px-3 py-2 text-xs text-slate-300"><WarrantyText w={s.warranty} /></td>
        <td className="px-3 py-2 text-xs text-slate-300">{s.link ? `${s.link.name || '—'}${s.link.confidence === 'low' ? ' ⚠' : ''}` : '—'}</td>
      </tr>
      {open && (
        <tr className="bg-slate-900/40">
          <td colSpan={12} className="px-6 py-4 space-y-3">
            {!d ? <div className="text-xs text-slate-500">{t('hw_loading')}</div> : (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <Cell k={t('hw_col_bmc')} v={val(d.bmc_ip, t) + (d.bmc_type ? ` (${d.bmc_type})` : '')} />
                  <Cell k={t('hw_col_bmc_ver')} v={val(d.bmc_version, t)} />
                  <Cell k="BIOS" v={val(d.bios_version, t)} />
                  <Cell k={t('hw_col_power')} v={d.power_state === 'on' ? t('hw_power_on') : d.power_state === 'off' ? t('hw_power_off') : t('hw_not_measured')} />
                  <Cell k={t('hw_col_form')} v={formFactorLabel(t, d.form_factor)} />
                  <Cell k="CPU / RAM" v={`${val(d.cpu_count, t)} / ${d.memory_gb != null ? d.memory_gb + ' GB' : t('hw_not_measured')}`} />
                  <Cell k={t('hw_col_match')} v={d.link ? t('hw_matched_by', { m: d.link.method, c: d.link.confidence === 'low' ? t('hw_conf_low') : t('hw_conf_exact') }) : '—'} />
                  <Cell k={t('hwi_managers')} v={d.manager ? `${d.manager.name} ${d.manager.version || ''}` : '—'} />
                </div>
                <FwStatusPanel serverId={s.id} status={d.firmware_status} hasData={(d.firmware || []).length > 0 || !!d.bmc_version || !!d.bios_version} />
                <FirmwareSection rows={d.firmware || []} readAt={d.firmware_collected_at} />
                {d.link && (
                  <button type="button" onClick={() => { if (window.confirm(t('hw_unlink_confirm'))) unlink.mutate() }} disabled={unlink.isPending}
                    className="text-xs px-2 py-1 rounded-sm border border-white/[0.1] text-slate-300 hover:text-white" data-testid="hw-unlink">
                    {t('hw_unlink')}
                  </button>
                )}
                {d.web_url && !detail.data?.demo && (
                  <a href={d.web_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200">
                    {t('hw_open_console')} <ExternalLink size={11} />
                  </a>
                )}
                {d.impact && (d.impact.vm_count > 0 || d.impact.cluster) && (
                  <div className="rounded-sm border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-100 space-y-0.5" data-testid="hw-impact">
                    <div className="font-medium">{t('hw_impact_title')}</div>
                    <div>{t('hw_impact_vms', { n: d.impact.vm_count, on: d.impact.vm_powered_on })}</div>
                    {(d.impact.services || []).length > 0 && (
                      <div>{t('hw_impact_services')}: {(d.impact.services as any[]).map(x => `${x.name} (${x.tier})`).join(', ')}</div>
                    )}
                    {d.impact.cluster && (
                      <div className={d.impact.cluster.ha_risk ? 'text-red-300' : ''}>
                        {t('hw_impact_cluster', { c: d.impact.cluster.name, n: d.impact.cluster.healthy_hosts, m: d.impact.cluster.hosts })}
                        {d.impact.cluster.ha_risk ? ` — ${t('hw_impact_ha_risk')}` : ''}
                      </div>
                    )}
                  </div>
                )}
                {(d.history || []).length > 0 && (
                  <div className="space-y-1" data-testid="hw-history">
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">{t('hw_history')}</div>
                    {d.history.slice(0, 8).map((h: any) => (
                      <div key={h.event_id} className="text-xs text-slate-300 flex gap-2">
                        <span className={h.severity === 'critical' ? 'text-red-300' : 'text-amber-300'}>{h.severity}</span>
                        <span className="text-slate-500 whitespace-nowrap">{h.opened_at ? new Date(h.opened_at).toLocaleString() : ''}</span>
                        <span className="truncate" title={h.title}>{h.title}</span>
                        <span className={h.resolved ? 'text-emerald-300' : 'text-red-300'}>{h.resolved ? t('hw_hist_resolved') : t('hw_hist_open')}</span>
                      </div>
                    ))}
                  </div>
                )}
                {(d.alerts || []).length > 0 && (
                  <div className="space-y-1">
                    <div className="text-[10px] uppercase tracking-wide text-slate-500">{t('hw_recent_alerts')}</div>
                    {d.alerts.slice(0, 8).map((a: any, i: number) => (
                      <div key={i} className="text-xs text-slate-300 flex gap-2">
                        <span className={a.severity === 'critical' ? 'text-red-300' : 'text-amber-300'}>{a.severity}</span>
                        <span className="text-slate-500">{a.occurred_at ? new Date(a.occurred_at).toLocaleString() : ''}</span>
                        <span className="truncate" title={a.message}>{a.message}</span>
                      </div>
                    ))}
                  </div>
                )}
                {/* Host donanım logları: eşleşmiş hedefe (Linux/ESXi) bağlanır, değilse portal kaydının kendisine */}
                <HwHostLogsCard kind={d.link ? d.link.kind : 'hw'} id={d.link ? d.link.id : s.id} showEmpty />
              </>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export default function HardwarePage() {
  const t = useT()
  const { hasHw, hasHwLogs } = useCapabilities()
  // Faz 3c: portal (OME/OneView) yok ama log kaynağı açık / log kaydı var → yalnız Loglar + BMC sekmeleri.
  const logsOnly = !hasHw && !!hasHwLogs
  const [tab, setTab] = useState<Tab>('servers')
  const [q, setQ] = useState('')
  const [health, setHealth] = useState('')
  const [vendor, setVendor] = useState('')
  const [matched, setMatched] = useState('')
  const [hostClass, setHostClass] = useState('')
  const [sort, setSort] = useState<{ by: string; dir: SortDir } | null>(null)
  // asc → desc → sıralamasız (varsayılan ad sırası)
  const toggleSort = (by: string) => setSort(cur => (!cur || cur.by !== by ? { by, dir: 'asc' } : cur.dir === 'asc' ? { by, dir: 'desc' } : null))

  const summary = useQuery<any>({ queryKey: ['hw-summary'], enabled: !logsOnly, queryFn: () => get('/summary'), refetchInterval: 60_000 })
  const enabled = !!summary.data?.enabled
  const servers = useQuery<any>({
    queryKey: ['hw-servers', q, health, vendor, matched, hostClass, sort?.by ?? '', sort?.dir ?? ''],
    enabled: enabled && tab === 'servers',
    queryFn: () => get(`/servers?limit=500&q=${encodeURIComponent(q)}&health=${health}&vendor=${vendor}&matched=${matched}&host_class=${hostClass}${sort ? `&sort_by=${sort.by}&sort_dir=${sort.dir}` : ''}`),
  })
  const encl = useQuery<any>({ queryKey: ['hw-encl'], enabled: enabled && tab === 'enclosures', queryFn: () => get('/enclosures') })
  const alerts = useQuery<any>({ queryKey: ['hw-alerts'], enabled: enabled && tab === 'alerts', queryFn: () => get('/alerts?grouped=true') })
  const unm = useQuery<any>({ queryKey: ['hw-unmatched'], enabled: enabled && tab === 'unmatched', queryFn: () => get('/unmatched') })
  const fnd = useQuery<any>({ queryKey: ['hw-findings'], enabled: enabled && tab === 'findings', queryFn: () => get('/findings') })
  const [wDays, setWDays] = useState('180')
  const war = useQuery<any>({ queryKey: ['hw-warranty', wDays], enabled: enabled && tab === 'warranty', queryFn: () => get(`/warranty-report?days=${wDays}`) })
  const qc = useQueryClient()
  const [linkErr, setLinkErr] = useState<string | null>(null)
  const refreshLinks = () => { ['hw-unmatched', 'hw-summary', 'hw-servers', 'hw-health'].forEach(k => qc.invalidateQueries({ queryKey: [k] })) }
  const link = useMutation({
    mutationFn: (v: { hw: number; kind: string; id: number }) => send('/links', 'POST', { hw_server_id: v.hw, target_kind: v.kind, target_id: v.id }),
    onSuccess: () => { setLinkErr(null); refreshLinks() },
    onError: (e: any) => setLinkErr(e.message),
  })
  const exportWarrantyCsv = () => {
    const rows = war.data?.items || []
    const head = ['name', 'vendor', 'model', 'serial', 'end_date', 'days_remaining', 'service_level', 'tier', 'target']
    const csv = [head.join(';'), ...rows.map((r: any) => head.map(h => String(r[h] ?? '').replace(/;/g, ',')).join(';'))].join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }))
    a.download = 'hardware-warranty.csv'
    a.click()
  }

  const sm = summary.data
  const hdr = <PageHeader title={t('hw_title')} subtitle={t('hw_sub')} actions={<Link to="/integrations/hardware" className="text-xs text-slate-400 hover:text-white">{t('hw_none_link')}</Link>} />

  if (logsOnly) {
    const lt: Tab = tab === 'bmc' ? 'bmc' : 'logs'
    return (
      <div className="p-6 space-y-5" data-testid="hw-logs-only">
        {hdr}
        <div className="text-xs text-slate-400 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2" data-testid="hw-logs-only-note">{t('hw_logs_only_note')}</div>
        <Tabs active={lt} onChange={id => setTab(id as Tab)} tabs={[
          { id: 'logs', label: t('hw_tab_logs') },
          { id: 'bmc', label: t('hw_tab_bmc') },
        ]} />
        {lt === 'logs' && <HwLogsTab />}
        {lt === 'bmc' && <HwBmcTab />}
      </div>
    )
  }

  if (summary.isLoading) return <div className="p-6 text-sm text-slate-500">{t('hw_loading')}</div>
  if (!hasHw || !enabled) {
    return (
      <div className="p-6 space-y-4 max-w-5xl">
        {hdr}
        <Panel><EmptyState icon={<Server size={28} />} text={t('hw_none')} /></Panel>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5">
      {hdr}
      {sm.demo && <DemoStrip />}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <Kpi label={t('hw_kpi_total')} value={sm.total} accent={NEON.blue} onClick={() => { setHealth(''); setMatched(''); setTab('servers') }} />
        <Kpi label={t('hw_kpi_matched')} value={sm.matched} accent={NEON.green} active={matched === 'yes'} onClick={() => { setMatched('yes'); setTab('servers') }} />
        <Kpi label={t('hw_kpi_unmatched')} value={sm.unmatched} accent={NEON.orange} active={matched === 'no'} onClick={() => { setMatched('no'); setTab('servers') }} />
        <Kpi label={t('hw_kpi_critical')} value={sm.by_health?.critical ?? 0} accent={NEON.red} active={health === 'critical'} onClick={() => { setHealth('critical'); setTab('servers') }} />
        <Kpi label={t('hw_kpi_warning')} value={sm.by_health?.warning ?? 0} accent={NEON.orange} active={health === 'warning'} onClick={() => { setHealth('warning'); setTab('servers') }} />
        <Kpi label={t('hw_kpi_alerts24')} value={sm.alerts_24h} accent={NEON.pink} onClick={() => setTab('alerts')} />
      </div>
      <div className="space-y-1">
        {(sm.providers || []).map((p: any) => (
          <div key={p.id} className="text-xs text-slate-400 flex gap-3 flex-wrap">
            <span className="text-slate-200">{p.label}</span>
            {p.auth_halted && <span className="text-red-300">{t('hw_prov_halted')}</span>}
            {p.stale && <span className="text-amber-300">{t('hw_prov_stale')}</span>}
            <span>{p.last_sync_at ? new Date(p.last_sync_at).toLocaleString() : '—'}</span>
          </div>
        ))}
      </div>

      <Tabs active={tab} onChange={id => setTab(id as Tab)} tabs={[
        { id: 'servers', label: t('hw_tab_servers'), count: sm.total },
        { id: 'enclosures', label: t('hw_tab_enclosures') },
        { id: 'alerts', label: t('hw_tab_alerts'), count: sm.active_alerts },
        { id: 'logs', label: t('hw_tab_logs') },
        { id: 'bmc', label: t('hw_tab_bmc') },
        { id: 'warranty', label: t('hw_tab_warranty') },
        { id: 'unmatched', label: t('hw_tab_unmatched'), count: sm.unmatched },
        { id: 'firmware', label: t('hw_tab_firmware') },
        { id: 'findings', label: t('hw_tab_findings') },
      ]} />

      {tab === 'servers' && (
        <Panel method="hw.inventory">
          <div className="px-3 pt-3 flex gap-1.5 flex-wrap items-center" data-testid="hw-class-chips" title={t('hw_class_hint')}>
            {[['', sm.total] as [string, number], ...HOST_CLASSES.filter(c => (sm.by_class?.[c] ?? 0) > 0).map(c => [c, sm.by_class[c]] as [string, number])].map(([c, n]) => (
              <button key={c || 'all'} type="button" data-testid={`hw-class-${c || 'all'}`} aria-pressed={hostClass === c}
                onClick={() => setHostClass(c)}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${hostClass === c ? 'bg-blue-600 border-blue-500 text-white' : 'border-white/[0.1] text-slate-300 hover:text-white hover:bg-white/[0.05]'}`}>
                {c ? t(`hw_class_${c}` as any) : t('hw_filter_all')} <span className="opacity-70">{n}</span>
              </button>
            ))}
          </div>
          <div className="p-3 flex gap-2 flex-wrap items-center border-b border-white/[0.06]">
            <SearchInput value={q} onChange={setQ} placeholder={t('hw_search')} width="w-80" />
            <Select value={health} onChange={setHealth}>
              <option value="">{t('hw_col_health')}: {t('hw_filter_all')}</option>
              {['ok', 'warning', 'critical', 'unknown'].map(h => <option key={h} value={h}>{t(`hw_health_${h}` as any)}</option>)}
            </Select>
            <Select value={vendor} onChange={setVendor}>
              <option value="">{t('hw_col_vendor')}: {t('hw_filter_all')}</option>
              <option value="dell">Dell</option>
              <option value="hpe">HPE</option>
            </Select>
            <Select value={matched} onChange={setMatched}>
              <option value="">{t('hw_col_match')}: {t('hw_filter_all')}</option>
              <option value="yes">{t('hw_kpi_matched')}</option>
              <option value="no">{t('hw_kpi_unmatched')}</option>
            </Select>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2 w-6" />
                  {SORT_COLS.map(([k, by]) => {
                    const active = sort?.by === by
                    const Icon = !active ? ArrowUpDown : sort!.dir === 'asc' ? ArrowUp : ArrowDown
                    return (
                      <th key={k} className="px-3 py-2 font-medium" aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                        <button
                          type="button"
                          data-testid={`hw-sort-${by}`}
                          onClick={() => toggleSort(by)}
                          title={t('hw_sort_hint')}
                          className={`inline-flex items-center gap-1 uppercase tracking-wide hover:text-slate-200 ${active ? 'text-sky-300' : ''}`}
                        >
                          {t(k as any)}
                          <Icon className={`w-3 h-3 ${active ? '' : 'opacity-40'}`} />
                        </button>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {(servers.data?.servers || []).map((s: any) => <ServerRow key={s.id} s={s} />)}
              </tbody>
            </table>
            {!servers.isLoading && !(servers.data?.servers || []).length && <EmptyState text={t('hw_rows_none')} />}
          </div>
        </Panel>
      )}

      {tab === 'enclosures' && (
        <div className="space-y-3">
          {(encl.data?.enclosures || []).map((e: any) => (
            <Panel key={e.id} title={<span className="flex items-center gap-2">{e.name} <HealthBadge health={e.health} /><span className="text-xs font-normal text-slate-400">{val(e.model, t)}</span><span className="text-xs font-normal text-slate-500" data-testid="hw-encl-bays">{t('hw_encl_bays', { bays: e.bay_count ?? '—', n: (e.servers || []).length })}</span></span>}>
              <div className="p-3 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
                {layoutBays(e.servers || [], e.empty_bays).map((c, i) => <BayBox key={`${c.bay}-${i}`} cell={c} />)}
                {!(e.servers || []).length && !(e.empty_bays || []).length && <div className="text-xs text-slate-500">{t('hw_rows_none')}</div>}
              </div>
            </Panel>
          ))}
          {(encl.data?.unassigned || []).length > 0 && (
            <Panel title={<span className="flex items-center gap-2">{t('hw_encl_unassigned')}<span className="text-xs font-normal text-slate-500">{t('hw_encl_unassigned_hint')}</span></span>}>
              <div className="p-3 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2" data-testid="hw-encl-unassigned">
                {(encl.data.unassigned as any[]).map(s => (
                  <div key={s.id} className="rounded-sm border border-white/[0.08] p-2 text-xs">
                    <div className="flex items-center justify-between gap-1"><span className="text-slate-400 truncate" title={s.enclosure || ''}>{s.enclosure || '—'}{s.bay ? ` / ${s.bay}` : ''}</span><HealthBadge health={s.health} /></div>
                    <div className="text-slate-100 truncate mt-1" title={s.name}>{s.name}</div>
                    <div className="text-slate-500 truncate">{val(s.model, t)}</div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
          {!encl.isLoading && !(encl.data?.enclosures || []).length && !(encl.data?.unassigned || []).length && <Panel><EmptyState text={t('hw_encl_empty')} /></Panel>}
        </div>
      )}

      {tab === 'alerts' && (
        <Panel method="hw.alarms">
          <div className="px-4 py-2 text-xs text-slate-500">{t('hw_alerts_group')}</div>
          <div className="divide-y divide-white/[0.05]">
            {(alerts.data?.groups || []).map((g: any) => (
              <div key={g.fingerprint} className="px-4 py-2.5 flex items-start gap-3">
                <span className={`text-[11px] mt-0.5 ${g.severity === 'critical' ? 'text-red-300' : 'text-amber-300'}`}>{g.severity}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-slate-100 wrap-break-word">{g.message || g.category}</div>
                  <div className="text-xs text-slate-500">{t('hw_alert_count', { n: g.count, s: g.server_count })}{g.examples?.length ? ` · ${g.examples.join(', ')}` : ''}</div>
                </div>
                <div className="text-xs text-slate-500 whitespace-nowrap">{g.last_at ? new Date(g.last_at).toLocaleString() : ''}</div>
              </div>
            ))}
            {!alerts.isLoading && !(alerts.data?.groups || []).length && <EmptyState text={t('hw_rows_none')} />}
          </div>
        </Panel>
      )}

      {tab === 'warranty' && (
        <Panel>
          <div className="p-3 flex gap-2 items-center flex-wrap border-b border-white/[0.06]">
            <Select value={wDays} onChange={setWDays}>
              {['90', '180', '365', '730'].map(d => <option key={d} value={d}>{t('hw_warranty_window', { n: d })}</option>)}
            </Select>
            <span className="text-xs text-slate-400">{t('hw_warranty_summary', { n: war.data?.total ?? 0, e: war.data?.expired ?? 0 })}</span>
            <button type="button" onClick={exportWarrantyCsv} disabled={!(war.data?.items || []).length}
              className="ml-auto text-xs px-2 py-1 rounded-sm border border-white/[0.1] text-slate-300 hover:text-white disabled:opacity-40">CSV</button>
          </div>
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-slate-500">
                {['hw_col_name', 'hw_col_vendor', 'hw_col_model', 'hw_col_serial', 'hw_col_warranty', 'hw_col_level', 'hw_col_tier'].map(k => <th key={k} className="px-3 py-2 font-medium">{t(k as any)}</th>)}
              </tr>
            </thead>
            <tbody>
              {(war.data?.items || []).map((r: any) => (
                <tr key={r.id} className="border-t border-white/[0.05]" data-testid="hw-warranty-row">
                  <td className="px-3 py-2 text-sm text-white">{r.name}</td>
                  <td className="px-3 py-2 text-xs text-slate-300 uppercase">{r.vendor}</td>
                  <td className="px-3 py-2 text-xs text-slate-300">{val(r.model, t)}</td>
                  <td className="px-3 py-2 text-xs text-slate-300">{val(r.serial, t)}</td>
                  <td className="px-3 py-2 text-xs"><WarrantyText w={{ end_date: r.end_date, expired: r.expired, days_remaining: r.days_remaining }} /></td>
                  <td className="px-3 py-2 text-xs text-slate-300">{val(r.service_level, t)}</td>
                  <td className="px-3 py-2 text-xs text-slate-300">{r.tier || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!war.isLoading && !(war.data?.items || []).length && <EmptyState text={t('hw_warranty_none')} />}
        </Panel>
      )}

      {tab === 'unmatched' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Panel title={t('hw_unmatched_hw')} method="hw.match">
            {linkErr && <div className="px-4 py-2 text-xs text-red-300" role="alert">{linkErr}</div>}
            <div className="divide-y divide-white/[0.05] max-h-[28rem] overflow-y-auto">
              {(unm.data?.hw || []).map((s: any) => (
                <div key={s.id} className="px-4 py-2 text-xs space-y-1" data-testid="hw-unmatched-row">
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-100">{s.name}</span>
                    <span className="text-slate-400">{s.vendor} · {val(s.model, t)} · {s.has_serial ? s.serial : t('hw_serial_missing')}</span>
                  </div>
                  {(s.candidates || []).length > 0 ? (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-slate-500">{t('hw_candidates')}:</span>
                      {s.candidates.map((c: any) => (
                        <button key={`${c.kind}-${c.id}`} type="button" disabled={link.isPending}
                          onClick={() => link.mutate({ hw: s.id, kind: c.kind, id: c.id })}
                          className="px-2 py-0.5 rounded-sm border border-blue-500/40 bg-blue-500/10 text-blue-200 hover:bg-blue-500/20"
                          title={t('hw_link_do')}>
                          {c.name} · {Math.round(c.score * 100)}% · {t('hw_link_do')}
                        </button>
                      ))}
                    </div>
                  ) : <div className="text-slate-500">{t('hw_no_candidates')}</div>}
                </div>
              ))}
              {!unm.isLoading && !(unm.data?.hw || []).length && <EmptyState text={t('hw_rows_none')} />}
            </div>
          </Panel>
          <Panel title={t('hw_unmatched_hosts')}>
            <div className="divide-y divide-white/[0.05] max-h-[28rem] overflow-y-auto">
              {(unm.data?.hosts || []).map((s: any) => (
                <div key={s.id} className="px-4 py-2 text-xs flex justify-between gap-2">
                  <span className="text-slate-100">{s.name}</span>
                  <span className="text-slate-400">{s.os_type || ''} · {s.hw_serial_collected ? t('hw_serial_collected') : t('hw_serial_missing')}</span>
                </div>
              ))}
              {!unm.isLoading && !(unm.data?.hosts || []).length && <EmptyState text={t('hw_rows_none')} />}
            </div>
            {unm.data?.note && <div className="px-4 py-2 text-[11px] text-slate-500 border-t border-white/[0.06]">{unm.data.note}</div>}
          </Panel>
        </div>
      )}

      {tab === 'logs' && <HwLogsTab />}

      {tab === 'bmc' && <HwBmcTab />}

      {tab === 'firmware' && <HwFirmwareTab />}

      {tab === 'findings' && (
        <Panel>
          <div className="divide-y divide-white/[0.05]">
            {(fnd.data?.findings || []).map((f: any, i: number) => (
              <div key={i} className="px-4 py-2.5">
                <div className="flex items-center gap-2 text-sm text-slate-100">
                  <span className={f.severity === 'critical' || f.severity === 'high' ? 'text-red-300' : 'text-amber-300'}>{f.severity}</span>
                  <span>{f.title}</span>
                  <span className="text-xs text-slate-500">· {f.entity_name}</span>
                </div>
                {f.detail && <div className="text-xs text-slate-400 mt-0.5">{f.detail}</div>}
                {f.recommendation && <div className="text-xs text-slate-500 mt-0.5">{f.recommendation}</div>}
              </div>
            ))}
            {!fnd.isLoading && !(fnd.data?.findings || []).length && <EmptyState text={t('hw_findings_none')} />}
          </div>
        </Panel>
      )}
    </div>
  )
}
