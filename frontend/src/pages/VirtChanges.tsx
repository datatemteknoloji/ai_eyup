import React, { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useT } from '../i18n/LocaleProvider'
import { GhostButton, Modal, NEON, PageHeader, PrimaryButton, SearchInput, Select, Tabs } from '../components/aiops/ui'
import { PageInfo, Panel, RunBar, apiSend, useInsights, useRole, type InsightsBase } from '../components/insights/insightsKit'
import { ColumnTable, type TableColumn } from '../components/ColumnTable'

const show = (v: unknown) => (v == null ? '∅' : typeof v === 'object' ? JSON.stringify(v) : String(v))
const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : '—')

/** Varlık anahtarına göre sorgu parametreleri (virt: platform+hypervisor_id, OCP: cluster_id). */
function entityParams(base: InsightsBase, o: { platform?: string; source_id?: number | null; entity_kind: string; entity_ref: string }) {
  const p = new URLSearchParams()
  if (base === 'ocp-insights') {
    if (o.source_id != null) p.set('cluster_id', String(o.source_id))
  } else {
    if (o.platform) p.set('platform', o.platform)
    if (o.source_id != null) p.set('hypervisor_id', String(o.source_id))
  }
  p.set('entity_kind', o.entity_kind)
  p.set('entity_ref', o.entity_ref)
  return p
}

function entityBody(base: InsightsBase, o: { platform?: string; source_id?: number | null; entity_kind: string; entity_ref: string }) {
  return base === 'ocp-insights'
    ? { cluster_id: o.source_id, entity_kind: o.entity_kind, entity_ref: o.entity_ref }
    : { platform: o.platform, hypervisor_id: o.source_id, entity_kind: o.entity_kind, entity_ref: o.entity_ref }
}

function DiffTable({ changes }: { changes: any[] }) {
  return (
    <table className="w-full text-xs font-mono">
      <tbody>
        {changes.map((x: any, i: number) => (
          <tr key={i} className="align-top">
            <td className="py-1 pr-3 text-slate-300 whitespace-nowrap">{x.path}</td>
            <td className="py-1 pr-3 text-slate-500">{x.op}</td>
            <td className="py-1 pr-3 text-red-300 break-all">{show(x.old)}</td>
            <td className="py-1 text-emerald-300 break-all">{show(x.new)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ChangeRow({ c, base, selected, onToggle }: { c: any; base: InsightsBase; selected: boolean; onToggle: () => void }) {
  const t = useT()
  const qc = useQueryClient()
  const { isOperator } = useRole()
  const [open, setOpen] = useState(false)
  const [msg, setMsg] = useState('')
  const refresh = () => qc.invalidateQueries({ queryKey: [base] })
  const baseline = async () => {
    try {
      await apiSend(base, '/baseline', 'POST', entityBody(base, c))
      setMsg(t('vi_ch_baselined'))
      refresh()
    } catch (err: any) { setMsg(err.message) }
  }
  // Baseline kaldırma (snapshot geçmişi korunur; sapma izleme durur).
  const clearBaseline = async () => {
    if (!window.confirm(t('vi_bl_clear_confirm'))) return
    try {
      await apiSend(base, `/baseline?${entityParams(base, c)}`, 'DELETE')
      setMsg(t('vi_ch_baseline_cleared'))
      refresh()
    } catch (err: any) { setMsg(err.message) }
  }
  const ack = async (undo = false) => {
    try {
      await apiSend(base, '/changes/ack', 'POST', { ids: [c.id], undo })
      refresh()
    } catch (err: any) { setMsg(err.message) }
  }
  const hasBaseline = c.is_baseline || c.has_baseline
  return (
    <>
      <tr className={`border-b border-white/[0.04] hover:bg-white/[0.02] cursor-pointer ${c.acked ? 'opacity-60' : ''}`} onClick={() => setOpen(!open)} data-testid="change-row">
        <td className="px-3 py-2 text-slate-500" onClick={e => e.stopPropagation()}>
          {isOperator
            ? <input type="checkbox" checked={selected} onChange={onToggle} aria-label="select" data-testid="change-select" />
            : (open ? <ChevronDown size={14} /> : <ChevronRight size={14} />)}
        </td>
        <td className="px-3 py-2 font-mono text-xs text-slate-300">{when(c.captured_at)}</td>
        <td className="px-3 py-2 text-xs text-slate-400">{c.platform} · {c.entity_kind}</td>
        <td className="px-3 py-2 font-mono text-xs text-white">{c.entity_name}{c.cluster_name ? <span className="text-slate-500"> · {c.cluster_name}</span> : null}</td>
        <td className="px-3 py-2 text-xs text-slate-400 truncate max-w-[26rem]">{(c.changes || []).map((x: any) => x.path).join(', ')}</td>
        <td className="px-3 py-2 font-mono text-xs text-blue-300">{c.change_count}</td>
        <td className="px-3 py-2 text-right" onClick={e => e.stopPropagation()}>
          <div className="flex items-center justify-end gap-2 flex-wrap">
            {hasBaseline
              ? <span className="text-[10px] text-emerald-400 border border-emerald-500/30 rounded-sm px-1" title={c.baseline_at || ''}>
                {c.baseline_by || c.baseline_at ? t('vi_ch_baseline_by', { u: c.baseline_by || '—', t: when(c.baseline_at) }) : 'baseline'}
              </span>
              : isOperator && <GhostButton onClick={baseline}>{t('vi_ch_set_baseline')}</GhostButton>}
            {isOperator && hasBaseline && <GhostButton onClick={clearBaseline}>{t('vi_ch_clear_baseline')}</GhostButton>}
            {isOperator && (c.acked
              ? <GhostButton onClick={() => ack(true)}>{t('vi_ch_unack_btn')}</GhostButton>
              : <GhostButton onClick={() => ack(false)}>{t('vi_ch_ack_btn')}</GhostButton>)}
          </div>
          {c.acked && <div className="text-[10px] text-slate-500 text-right">{t('vi_ch_ack_by', { u: c.ack_by || '—', t: when(c.ack_at) })}</div>}
          {msg && <div className="text-[10px] text-blue-300">{msg}</div>}
        </td>
      </tr>
      {open && (
        <tr className="bg-black/20 border-b border-white/[0.04]">
          <td />
          <td colSpan={6} className="px-3 py-3">
            <DiffTable changes={c.changes || []} />
            <div className="text-[11px] text-slate-500 mt-2">{t('vi_ch_prev')}: {when(c.previous_at)}</div>
          </td>
        </tr>
      )}
    </>
  )
}

/** Mevcut yapılandırmayı toplu baseline yapar (operator). Hiçbir sisteme yazılmaz; yalnız ainew'de işaret konur.
 *  Zaten baseline varsa üzerine yazılacağı açıkça onaylatılır. */
function BaselineAll({ base, existing }: { base: InsightsBase; existing: number }) {
  const t = useT()
  const qc = useQueryClient()
  const { isOperator } = useRole()
  const ocp = base === 'ocp-insights'
  const kinds = ocp ? ['node', 'mcp', 'platform', 'cluster', 'operator'] : ['host', 'cluster', 'datastore', 'platform', 'vm']
  const rec = ocp ? ['node', 'mcp', 'platform', 'cluster'] : ['host', 'cluster', 'datastore', 'platform']
  const [open, setOpen] = useState(false)
  const [scope, setScope] = useState('recommended')
  const [busy, setBusy] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [msg, setMsg] = useState('')
  if (!isOperator) return null
  const needsConfirm = existing > 0
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
      <GhostButton accent={NEON.blue} onClick={() => { setMsg(''); setConfirmed(false); setOpen(true) }}>{t('vi_bl_btn')}</GhostButton>
      {open && (
        <Modal title={t('vi_bl_btn')} onClose={() => setOpen(false)} maxWidth="max-w-lg"
          footer={<div className="flex items-center justify-between gap-3">
            <span className="text-xs text-blue-300">{msg}</span>
            <PrimaryButton accent={NEON.blue} onClick={run} disabled={busy || (needsConfirm && !confirmed)}>{busy ? '…' : t('vi_bl_apply')}</PrimaryButton>
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
            {needsConfirm && (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 space-y-2" data-testid="baseline-overwrite-warning">
                <p>{t('vi_bl_confirm_overwrite', { n: existing })}</p>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} data-testid="baseline-overwrite-confirm" />
                  {t('vi_bl_confirm_check')}
                </label>
              </div>
            )}
          </div>
        </Modal>
      )}
    </>
  )
}

type BaselineItem = {
  platform: string; source_id: number | null; entity_kind: string; entity_ref: string
  entity_name?: string; cluster_name?: string | null
  baseline_at?: string | null; baseline_by?: string | null; latest_at?: string | null
  drift_count: number; status: 'same' | 'drift'; changes?: any[]
}

/** Baseline'ı olan varlıklar: kim/ne zaman işaretledi + CANLI sapma + baseline ↔ güncel fark. */
function BaselinesView({ base, items, loading, emptyText }: { base: InsightsBase; items: BaselineItem[]; loading: boolean; emptyText?: string }) {
  const t = useT()
  const qc = useQueryClient()
  const { isOperator } = useRole()
  const [sel, setSel] = useState<BaselineItem | null>(null)
  const [msg, setMsg] = useState('')
  const ocp = base === 'ocp-insights'
  const refresh = () => qc.invalidateQueries({ queryKey: [base] })
  const columns: TableColumn<BaselineItem>[] = [
    {
      id: 'entity', label: t('vi_col_entity'), text: i => `${i.entity_name || i.entity_ref} ${i.cluster_name || ''}`,
      render: i => <span className="font-mono text-white">{i.entity_name || i.entity_ref}{i.cluster_name ? <span className="text-slate-500"> · {i.cluster_name}</span> : null}</span>,
    },
    { id: 'type', label: t('vi_col_type'), text: i => (ocp ? i.entity_kind : `${i.platform} · ${i.entity_kind}`) },
    { id: 'by', label: t('vi_bl_col_by'), text: i => i.baseline_by || '' },
    { id: 'at', label: t('vi_bl_col_at'), text: i => when(i.baseline_at), num: i => (i.baseline_at ? Date.parse(i.baseline_at) : null) },
    { id: 'latest', label: t('vi_bl_col_latest'), text: i => when(i.latest_at), num: i => (i.latest_at ? Date.parse(i.latest_at) : null) },
    { id: 'drift', label: t('vi_bl_col_drift'), text: i => String(i.drift_count), num: i => i.drift_count },
    {
      id: 'status', label: t('vi_bl_col_status'), text: i => i.status,
      render: i => (
        <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase ${i.status === 'drift'
          ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'}`}>
          {i.status === 'drift' ? t('vi_bl_status_drift') : t('vi_bl_status_same')}
        </span>
      ),
    },
  ]
  const act = async (fn: () => Promise<unknown>) => {
    try { await fn(); setSel(null); refresh() } catch (e: any) { setMsg(e.message) }
  }
  return (
    <div className="space-y-2" data-testid="baselines-view">
      <ColumnTable
        testId="baselines"
        rows={items}
        columns={columns}
        rowKey={i => `${i.platform}|${i.source_id}|${i.entity_kind}|${i.entity_ref}`}
        searchPlaceholder={t('vi_col_entity')}
        empty={emptyText || t('vi_bl_empty')}
        loading={loading}
        onRowClick={i => { setMsg(''); setSel(i) }}
        rowTestId="baseline-row"
        maxHeightClass="max-h-[32rem]"
      />
      {sel && (
        <Modal title={t('vi_bl_compare_title')} subtitle={`${sel.entity_name || sel.entity_ref} · ${sel.entity_kind}`} onClose={() => setSel(null)} maxWidth="max-w-3xl"
          footer={<div className="flex items-center justify-between gap-3">
            <span className="text-xs text-blue-300">{msg}</span>
            {isOperator && (
              <div className="flex gap-2">
                <GhostButton onClick={() => act(() => apiSend(base, `/baseline?${entityParams(base, sel)}`, 'DELETE'))}>{t('vi_ch_clear_baseline')}</GhostButton>
                <PrimaryButton accent={NEON.blue} onClick={() => act(() => apiSend(base, '/baseline', 'POST', entityBody(base, sel)))}>{t('vi_bl_refresh')}</PrimaryButton>
              </div>
            )}
          </div>}>
          <div className="px-5 py-4 space-y-3 text-xs text-slate-300">
            <div className="grid grid-cols-2 gap-3">
              <div><div className="text-slate-500">{t('vi_bl_baseline_snap')}</div><div>{when(sel.baseline_at)} · {sel.baseline_by || '—'}</div></div>
              <div><div className="text-slate-500">{t('vi_bl_latest_snap')}</div><div>{when(sel.latest_at)}</div></div>
            </div>
            {(sel.changes || []).length > 0
              ? <DiffTable changes={sel.changes || []} />
              : <p className="text-slate-400">{t('vi_bl_no_diff')}</p>}
          </div>
        </Modal>
      )}
    </div>
  )
}

export function ChangesView({ base }: { base: InsightsBase }) {
  const ocp = base === 'ocp-insights'
  const t = useT()
  const qc = useQueryClient()
  const { isOperator } = useRole()
  const [tab, setTab] = useState('changes')
  const [days, setDays] = useState('30')
  const [platform, setPlatform] = useState('')
  const [kind, setKind] = useState('')
  const [entity, setEntity] = useState('')
  const [ackMode, setAckMode] = useState('hide')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [ackMsg, setAckMsg] = useState('')
  const qs = new URLSearchParams({ days, ack: ackMode })
  if (platform && !ocp) qs.set('platform', platform)
  if (kind) qs.set('entity_kind', kind)
  if (entity.trim()) qs.set('entity', entity.trim())
  const q = useInsights<any>(base, `/changes?${qs}`)
  const bl = useInsights<{ items: BaselineItem[]; drifted: number }>(base, '/baseline?diff=true')
  const sum = useInsights<any>(base, '/summary')
  const rows: any[] = q.data?.changes || []
  const baselineCount = typeof q.data?.baseline_count === 'number' ? q.data.baseline_count : null
  const drifted = typeof q.data?.drifted_count === 'number' ? q.data.drifted_count : (bl.data?.drifted ?? 0)
  const byKind = (q.data?.baseline_by_kind || {}) as Record<string, number>
  const kindLine = Object.entries(byKind).filter(([, n]) => n > 0).map(([k, n]) => `${k} ${n}`).join(', ')
  const unbasedKinds = Object.entries((q.data?.changed_unbaselined_kinds || {}) as Record<string, number>).map(([k, n]) => `${k} ${n}`).join(', ')
  const toggle = (id: number) => setSelected(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const ackSelected = async () => {
    try {
      await apiSend(base, '/changes/ack', 'POST', { ids: [...selected], undo: ackMode === 'only' })
      setSelected(new Set()); setAckMsg('')
      qc.invalidateQueries({ queryKey: [base] })
    } catch (e: any) { setAckMsg(e.message) }
  }
  return (
    <div className="space-y-5">
      <PageHeader title={t('vi_ch_page')} titleExtra={<PageInfo id={ocp ? 'oi_ch' : 'vi_ch'} titleKey="vi_ch_page" />} subtitle={ocp ? t('oi_ch_sub') : t('vi_ch_sub')} actions={<RunBar base={base} lastRun={sum.data?.last_run} />} />
      <Tabs active={tab} onChange={setTab} tabs={[
        { id: 'changes', label: t('vi_ch_tab_changes'), count: rows.length },
        { id: 'drift', label: t('vi_ch_tab_drift'), count: drifted },
        { id: 'baselines', label: t('vi_ch_tab_baselines'), count: baselineCount ?? 0 },
      ]} />
      <div className="text-[11px] text-slate-500">{t('vi_ch_history_vs_drift')}</div>
      {baselineCount != null && (
        <div className="rounded-lg px-3 py-2 text-sm space-y-1" data-testid="baseline-banner" style={{ color: 'var(--theme-foreground)', background: 'color-mix(in srgb, var(--theme-success-fg) 12%, var(--theme-card))', border: '1px solid color-mix(in srgb, var(--theme-success-fg) 45%, var(--theme-border))' }}>
          <div>
            {baselineCount > 0
              ? t('vi_bl_summary', { n: baselineCount, k: kindLine, t: when(q.data?.baseline_marked_at), u: q.data?.baseline_marked_by || '—', d: drifted })
              : t('vi_bl_marked_none')}
          </div>
          {baselineCount > 0 && drifted === 0 && rows.length > 0 && <div className="text-xs opacity-80" data-testid="zero-drift-note">{t('vi_ch_zero_drift_note', { n: baselineCount })}</div>}
          {(q.data?.changed_unbaselined ?? 0) > 0 && <div className="text-xs text-amber-300" data-testid="unbaselined-note">{t('vi_ch_unbaselined_note', { n: q.data.changed_unbaselined, k: unbasedKinds })}</div>}
        </div>
      )}
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
              {(ocp ? ['cluster', 'node', 'mcp', 'operator', 'platform'] : ['cluster', 'host', 'datastore', 'vm']).map(k => <option key={k} value={k}>{k}</option>)}
            </Select>
            <Select value={ackMode} onChange={v => { setAckMode(v); setSelected(new Set()) }}>
              <option value="hide">{t('vi_ch_ack_hide')}</option>
              <option value="all">{t('vi_ch_ack_all')}</option>
              <option value="only">{t('vi_ch_ack_only')}</option>
            </Select>
            <SearchInput value={entity} onChange={setEntity} placeholder={t('vi_col_entity')} />
            <div className="ml-auto flex items-center gap-2">
              {isOperator && selected.size > 0 && (
                <GhostButton onClick={ackSelected}>{ackMode === 'only' ? t('vi_ch_unack_btn') : t('vi_ch_ack_selected', { n: selected.size })}</GhostButton>
              )}
              <BaselineAll base={base} existing={baselineCount ?? 0} />
            </div>
          </div>
          {ackMsg && <div className="text-xs text-red-300">{ackMsg}</div>}
          {ackMode === 'hide' && (q.data?.acked_total ?? 0) > 0 && (
            <div className="text-[11px] text-slate-500" data-testid="acked-hidden">{t('vi_ch_acked_hidden', { n: q.data.acked_total })}</div>
          )}
          <Panel method="drift.changes">
            {q.isLoading ? <div className="p-6 text-sm text-slate-400">{t('loading')}</div> : rows.length === 0 ? (
              <div className="py-10 text-center text-sm text-slate-500 space-y-1">
                <div>{t('vi_ch_none')}</div>
                {q.data?.empty_reason && <div className="text-xs text-slate-400">{t('vi_ch_empty_baseline')}</div>}
              </div>
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
                <tbody>{rows.map(c => <ChangeRow key={c.id} c={c} base={base} selected={selected.has(c.id)} onToggle={() => toggle(c.id)} />)}</tbody>
              </table>
            )}
          </Panel>
          <div className="text-[11px] text-slate-500">{t('vi_ch_note')}</div>
        </>
      )}
      {tab === 'drift' && (
        <Panel>
          <BaselinesView base={base} items={(bl.data?.items || []).filter(i => i.status === 'drift')} loading={bl.isLoading}
            emptyText={(baselineCount ?? 0) > 0 ? t('vi_ch_no_drift_set') : t('vi_ch_no_drift')} />
        </Panel>
      )}
      {tab === 'baselines' && (
        <Panel><BaselinesView base={base} items={bl.data?.items || []} loading={bl.isLoading} /></Panel>
      )}
    </div>
  )
}

export default function VirtChanges() {
  return <ChangesView base="virt-insights" />
}
