import React, { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useT } from '../i18n/LocaleProvider'
import { GhostButton, Modal, NEON, PageHeader, PrimaryButton, SearchInput, Select, Tabs } from '../components/aiops/ui'
import { FindingsTable, PageInfo, Panel, RunBar, apiSend, useInsights, useRole, type Finding, type InsightsBase } from '../components/insights/insightsKit'

const show = (v: unknown) => (v == null ? '∅' : typeof v === 'object' ? JSON.stringify(v) : String(v))

function ChangeRow({ c, base }: { c: any; base: InsightsBase }) {
  const t = useT()
  const qc = useQueryClient()
  const { isOperator } = useRole()
  const [open, setOpen] = useState(false)
  const [msg, setMsg] = useState('')
  const baseline = async () => {
    try {
      await apiSend(base, '/baseline', 'POST', base === 'ocp-insights'
        ? { cluster_id: c.source_id, entity_kind: c.entity_kind, entity_ref: c.entity_ref }
        : { platform: c.platform, hypervisor_id: c.source_id, entity_kind: c.entity_kind, entity_ref: c.entity_ref })
      setMsg(t('vi_ch_baselined'))
      qc.invalidateQueries({ queryKey: [base] })
    } catch (err: any) { setMsg(err.message) }
  }
  return (
    <>
      <tr className="border-b border-white/[0.04] hover:bg-white/[0.02] cursor-pointer" onClick={() => setOpen(!open)}>
        <td className="px-3 py-2 text-slate-500">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
        <td className="px-3 py-2 font-mono text-xs text-slate-300">{c.captured_at ? new Date(c.captured_at).toLocaleString() : '—'}</td>
        <td className="px-3 py-2 text-xs text-slate-400">{c.platform} · {c.entity_kind}</td>
        <td className="px-3 py-2 font-mono text-xs text-white">{c.entity_name}{c.cluster_name ? <span className="text-slate-500"> · {c.cluster_name}</span> : null}</td>
        <td className="px-3 py-2 text-xs text-slate-400 truncate max-w-[26rem]">{(c.changes || []).map((x: any) => x.path).join(', ')}</td>
        <td className="px-3 py-2 font-mono text-xs text-blue-300">{c.change_count}</td>
        <td className="px-3 py-2 text-right" onClick={e => e.stopPropagation()}>
          {c.is_baseline ? <span className="text-[10px] text-emerald-400 border border-emerald-500/30 rounded px-1">baseline</span>
            : isOperator && <GhostButton onClick={baseline}>{t('vi_ch_set_baseline')}</GhostButton>}
          {msg && <div className="text-[10px] text-blue-300">{msg}</div>}
        </td>
      </tr>
      {open && (
        <tr className="bg-black/20 border-b border-white/[0.04]">
          <td />
          <td colSpan={6} className="px-3 py-3">
            <table className="w-full text-xs font-mono">
              <tbody>
                {(c.changes || []).map((x: any, i: number) => (
                  <tr key={i} className="align-top">
                    <td className="py-1 pr-3 text-slate-300 whitespace-nowrap">{x.path}</td>
                    <td className="py-1 pr-3 text-slate-500">{x.op}</td>
                    <td className="py-1 pr-3 text-red-300 break-all">{show(x.old)}</td>
                    <td className="py-1 text-emerald-300 break-all">{show(x.new)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="text-[11px] text-slate-500 mt-2">{t('vi_ch_prev')}: {c.previous_at ? new Date(c.previous_at).toLocaleString() : '—'}</div>
          </td>
        </tr>
      )}
    </>
  )
}


/** Mevcut yapılandırmayı toplu baseline yapar (operator). Hiçbir sisteme yazılmaz; yalnız ainew'de işaret konur. */
function BaselineAll({ base }: { base: InsightsBase }) {
  const t = useT()
  const qc = useQueryClient()
  const { isOperator } = useRole()
  const ocp = base === 'ocp-insights'
  const kinds = ocp ? ['node', 'mcp', 'platform', 'cluster', 'operator'] : ['host', 'cluster', 'datastore', 'platform', 'vm']
  const rec = ocp ? ['node', 'mcp', 'platform', 'cluster'] : ['host', 'cluster', 'datastore', 'platform']
  const [open, setOpen] = useState(false)
  const [scope, setScope] = useState('recommended')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  if (!isOperator) return null
  const run = async () => {
    setBusy(true); setMsg('')
    try {
      const list: (string | undefined)[] = scope === 'recommended' ? rec : scope === 'all' ? [undefined] : [scope]
      let n = 0
      for (const k of list) {
        const r = await apiSend<{ count: number }>(base, '/baseline', 'POST', k ? { entity_kind: k } : {})
        n += r.count || 0
      }
      setMsg(t('vi_bl_done', { n }))
      qc.invalidateQueries({ queryKey: [base] })
    } catch (e: any) { setMsg(e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <GhostButton accent={NEON.blue} onClick={() => { setMsg(''); setOpen(true) }}>{t('vi_bl_btn')}</GhostButton>
      {open && (
        <Modal title={t('vi_bl_btn')} onClose={() => setOpen(false)} maxWidth="max-w-lg"
          footer={<div className="flex items-center justify-between gap-3">
            <span className="text-xs text-blue-300">{msg}</span>
            <PrimaryButton accent={NEON.blue} onClick={run} disabled={busy}>{busy ? '…' : t('vi_bl_apply')}</PrimaryButton>
          </div>}>
          <div className="px-5 py-4 space-y-3 text-sm text-slate-300">
            <p className="whitespace-pre-line">{t('vi_bl_desc')}</p>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              {t('vi_bl_scope')}
              <Select value={scope} onChange={setScope}>
                <option value="recommended">{t('vi_bl_recommended', { k: rec.join(', ') })}</option>
                {kinds.map(k => <option key={k} value={k}>{k}</option>)}
                <option value="all">{t('vi_bl_all')}</option>
              </Select>
            </label>
          </div>
        </Modal>
      )}
    </>
  )
}

export function ChangesView({ base }: { base: InsightsBase }) {
  const ocp = base === 'ocp-insights'
  const t = useT()
  const [tab, setTab] = useState('changes')
  const [days, setDays] = useState('30')
  const [platform, setPlatform] = useState('')
  const [kind, setKind] = useState('')
  const [entity, setEntity] = useState('')
  const qs = new URLSearchParams({ days })
  if (platform && !ocp) qs.set('platform', platform)
  if (kind) qs.set('entity_kind', kind)
  if (entity.trim()) qs.set('entity', entity.trim())
  const q = useInsights<any>(base, `/changes?${qs}`)
  const drift = useInsights<{ findings: Finding[] }>(base, '/findings?category=drift')
  const sum = useInsights<any>(base, '/summary')
  const rows: any[] = q.data?.changes || []
  return (
    <div className="space-y-5">
      <PageHeader title={t('vi_ch_page')} titleExtra={<PageInfo id={ocp ? 'oi_ch' : 'vi_ch'} titleKey="vi_ch_page" />} subtitle={ocp ? t('oi_ch_sub') : t('vi_ch_sub')} actions={<RunBar base={base} lastRun={sum.data?.last_run} />} />
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: 'changes', label: t('vi_ch_tab_changes'), count: rows.length },
        { id: 'drift', label: t('vi_ch_tab_drift'), count: drift.data?.findings?.length ?? 0 },
      ]} />
      {tab === 'changes' && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={days} onChange={setDays}>
              {['1', '7', '30', '90'].map(d => <option key={d} value={d}>{t('vi_ch_days', { n: d })}</option>)}
            </Select>
            {!ocp && (
              <Select value={platform} onChange={setPlatform}>
                <option value="">{t('vi_all_platforms')}</option>
                <option value="vmware">VMware</option>
                <option value="olvm">OLVM</option>
                <option value="ocp_virt">OpenShift Virtualization</option>
              </Select>
            )}
            <Select value={kind} onChange={setKind}>
              <option value="">{t('vi_all')}</option>
              {(ocp ? ['cluster', 'node', 'mcp', 'operator', 'platform'] : ['cluster', 'host', 'vm']).map(k => <option key={k} value={k}>{k}</option>)}
            </Select>
            <SearchInput value={entity} onChange={setEntity} placeholder={t('vi_col_entity')} />
            <div className="ml-auto"><BaselineAll base={base} /></div>
          </div>
          <Panel>
            {q.isLoading ? <div className="p-6 text-sm text-slate-400">{t('loading')}</div> : rows.length === 0 ? (
              <div className="py-10 text-center text-sm text-slate-500">{t('vi_ch_none')}</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
                    <th className="px-3 py-2 w-6" />
                    <th className="px-3 py-2">{t('vi_ch_when')}</th>
                    <th className="px-3 py-2">{t('vi_col_type')}</th>
                    <th className="px-3 py-2">{t('vi_col_entity')}</th>
                    <th className="px-3 py-2">{t('vi_ch_fields')}</th>
                    <th className="px-3 py-2">#</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>{rows.map(c => <ChangeRow key={c.id} c={c} base={base} />)}</tbody>
              </table>
            )}
          </Panel>
          <div className="text-[11px] text-slate-500">{t('vi_ch_note')}</div>
        </>
      )}
      {tab === 'drift' && (
        <Panel><FindingsTable base={base} rows={drift.data?.findings || []} emptyText={t('vi_ch_no_drift')} showPlatform={!ocp} /></Panel>
      )}
    </div>
  )
}

export default function VirtChanges() {
  return <ChangesView base="virt-insights" />
}
