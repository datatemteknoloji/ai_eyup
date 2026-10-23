import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, ExternalLink, Server } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'
import { useCapabilities } from '../hooks/useCapabilities'
import { EmptyState, Kpi, NEON, PageHeader, SearchInput, Select, Tabs } from '../components/aiops/ui'
import { Panel } from '../components/insights/insightsKit'
import { DemoStrip, HealthBadge, WarrantyText, formFactorLabel, val } from '../components/hardware/hwUi'

async function get(path: string) {
  const r = await fetch(`${API_BASE_URL}/hw${path}`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

type Tab = 'servers' | 'enclosures' | 'alerts' | 'unmatched' | 'findings'

const Cell: React.FC<{ k: string; v: React.ReactNode }> = ({ k, v }) => (
  <div>
    <div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div>
    <div className="text-xs text-slate-100 break-all">{v}</div>
  </div>
)

const ServerRow: React.FC<{ s: any }> = ({ s }) => {
  const t = useT()
  const [open, setOpen] = useState(false)
  const detail = useQuery<any>({ queryKey: ['hw-server', s.id], enabled: open, queryFn: () => get(`/servers/${s.id}`) })
  const d = detail.data?.server
  return (
    <>
      <tr className="border-t border-white/[0.05] hover:bg-white/[0.03] cursor-pointer" onClick={() => setOpen(!open)} data-testid="hw-row">
        <td className="px-3 py-2">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
        <td className="px-3 py-2 text-sm text-white">{s.name}</td>
        <td className="px-3 py-2 text-xs text-slate-300 uppercase">{s.vendor}</td>
        <td className="px-3 py-2 text-xs text-slate-300">{val(s.model, t)}</td>
        <td className="px-3 py-2 text-xs text-slate-300">{val(s.serial, t)}</td>
        <td className="px-3 py-2 text-xs text-slate-300">{val(s.bmc_ip, t)}</td>
        <td className="px-3 py-2"><HealthBadge health={s.health} /></td>
        <td className="px-3 py-2 text-xs text-slate-300">{s.enclosure_name ? `${s.enclosure_name}${s.bay ? ' / ' + s.bay : ''}` : formFactorLabel(t, s.form_factor)}</td>
        <td className="px-3 py-2 text-xs text-slate-300"><WarrantyText w={s.warranty} /></td>
        <td className="px-3 py-2 text-xs text-slate-300">{s.link ? `${s.link.name || '—'}${s.link.confidence === 'low' ? ' ⚠' : ''}` : '—'}</td>
      </tr>
      {open && (
        <tr className="bg-slate-900/40">
          <td colSpan={10} className="px-6 py-4 space-y-3">
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
                {d.web_url && !detail.data?.demo && (
                  <a href={d.web_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs text-blue-300 hover:text-blue-200">
                    {t('hw_open_console')} <ExternalLink size={11} />
                  </a>
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
  const { hasHw } = useCapabilities()
  const [tab, setTab] = useState<Tab>('servers')
  const [q, setQ] = useState('')
  const [health, setHealth] = useState('')
  const [vendor, setVendor] = useState('')
  const [matched, setMatched] = useState('')

  const summary = useQuery<any>({ queryKey: ['hw-summary'], queryFn: () => get('/summary'), refetchInterval: 60_000 })
  const enabled = !!summary.data?.enabled
  const servers = useQuery<any>({
    queryKey: ['hw-servers', q, health, vendor, matched],
    enabled: enabled && tab === 'servers',
    queryFn: () => get(`/servers?limit=500&q=${encodeURIComponent(q)}&health=${health}&vendor=${vendor}&matched=${matched}`),
  })
  const encl = useQuery<any>({ queryKey: ['hw-encl'], enabled: enabled && tab === 'enclosures', queryFn: () => get('/enclosures') })
  const alerts = useQuery<any>({ queryKey: ['hw-alerts'], enabled: enabled && tab === 'alerts', queryFn: () => get('/alerts?grouped=true') })
  const unm = useQuery<any>({ queryKey: ['hw-unmatched'], enabled: enabled && tab === 'unmatched', queryFn: () => get('/unmatched') })
  const fnd = useQuery<any>({ queryKey: ['hw-findings'], enabled: enabled && tab === 'findings', queryFn: () => get('/findings') })

  const sm = summary.data
  const hdr = <PageHeader title={t('hw_title')} subtitle={t('hw_sub')} actions={<Link to="/integrations/hardware" className="text-xs text-slate-400 hover:text-white">{t('hw_none_link')}</Link>} />

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
        { id: 'unmatched', label: t('hw_tab_unmatched'), count: sm.unmatched },
        { id: 'findings', label: t('hw_tab_findings') },
      ]} />

      {tab === 'servers' && (
        <Panel method="hw.inventory">
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
                  {['hw_col_name', 'hw_col_vendor', 'hw_col_model', 'hw_col_serial', 'hw_col_bmc', 'hw_col_health', 'hw_col_enclosure', 'hw_col_warranty', 'hw_col_match'].map(k => (
                    <th key={k} className="px-3 py-2 font-medium">{t(k as any)}</th>
                  ))}
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
            <Panel key={e.id} title={<span className="flex items-center gap-2">{e.name} <HealthBadge health={e.health} /><span className="text-xs font-normal text-slate-400">{val(e.model, t)}</span></span>}>
              <div className="p-3 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
                {(e.servers || []).map((s: any) => (
                  <div key={s.id} className="rounded border border-white/[0.08] p-2 text-xs">
                    <div className="flex items-center justify-between gap-1"><span className="text-slate-400">#{s.bay ?? '—'}</span><HealthBadge health={s.health} /></div>
                    <div className="text-slate-100 truncate mt-1" title={s.name}>{s.name}</div>
                    <div className="text-slate-500 truncate">{val(s.model, t)}</div>
                  </div>
                ))}
                {!(e.servers || []).length && <div className="text-xs text-slate-500">{t('hw_rows_none')}</div>}
              </div>
            </Panel>
          ))}
          {!encl.isLoading && !(encl.data?.enclosures || []).length && <Panel><EmptyState text={t('hw_encl_empty')} /></Panel>}
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
                  <div className="text-sm text-slate-100 break-words">{g.message || g.category}</div>
                  <div className="text-xs text-slate-500">{t('hw_alert_count', { n: g.count, s: g.server_count })}{g.examples?.length ? ` · ${g.examples.join(', ')}` : ''}</div>
                </div>
                <div className="text-xs text-slate-500 whitespace-nowrap">{g.last_at ? new Date(g.last_at).toLocaleString() : ''}</div>
              </div>
            ))}
            {!alerts.isLoading && !(alerts.data?.groups || []).length && <EmptyState text={t('hw_rows_none')} />}
          </div>
        </Panel>
      )}

      {tab === 'unmatched' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Panel title={t('hw_unmatched_hw')} method="hw.match">
            <div className="divide-y divide-white/[0.05] max-h-[28rem] overflow-y-auto">
              {(unm.data?.hw || []).map((s: any) => (
                <div key={s.id} className="px-4 py-2 text-xs flex justify-between gap-2">
                  <span className="text-slate-100">{s.name}</span>
                  <span className="text-slate-400">{s.vendor} · {val(s.model, t)} · {s.has_serial ? s.serial : t('hw_serial_missing')}</span>
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
