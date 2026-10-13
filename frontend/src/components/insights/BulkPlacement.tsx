import React, { useState } from 'react'
import { Download, Plus, Trash2 } from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'
import { GhostButton, NEON } from '../aiops/ui'
import { apiSend, fmt } from './insightsKit'
import { LimitChip } from './WhatIfResults'
import { TermHint } from './InfoDot'

export type Profile = { id: number; name: string; vcpu: string; memory_gb: string; disk_gb: string; count: string; group: string }

const MAX_ROWS = 50
const TONE: Record<string, string> = { ok: 'text-emerald-400', warn: 'text-amber-400', fail: 'text-red-400' }
const CSV_HEAD = ['cluster', 'hypervisor', 'vm', 'profile', 'group', 'vcpu', 'memory_gb', 'disk_gb', 'host', 'datastore', 'status', 'reason']

/** CSV hücresi: virgül/tırnak/satır sonu varsa tırnakla; formül enjeksiyonuna karşı =,+,-,@ ile başlayanı ' ile öne al. */
export function csvCell(v: unknown): string {
  let s = v == null ? '' : String(v)
  if (/^[=+\-@\t\r]/.test(s) && typeof v === 'string') s = `'${s}`
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** Bir veya birden çok cluster sonucunu CSV'ye çevirir (yerleşenler + yerleşemeyenler). Backend alanları aynen yazılır. */
export function planToCsv(results: any[]): string {
  const lines = [CSV_HEAD.join(',')]
  for (const r of results) {
    for (const p of r.plan || []) {
      lines.push([r.cluster, r.hypervisor, p.vm, p.profile, p.group, p.vcpu, p.memory_gb, p.disk_gb, p.host, p.datastore, 'placed', '']
        .map(csvCell).join(','))
    }
    for (const u of r.unplaced || []) {
      lines.push([r.cluster, r.hypervisor, u.vm, u.profile, u.group, '', u.memory_gb, '', '', '', 'unplaced', u.reason].map(csvCell).join(','))
    }
  }
  return lines.join('\r\n')
}

function download(name: string, text: string) {
  const blob = new Blob(['\ufeff' + text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name; a.click()
  URL.revokeObjectURL(url)
}

const safeName = (s: string) => s.replace(/[^A-Za-z0-9._-]+/g, '_')

/** Profil satırlarını backend gövdesine çevirir. Geçersizse Türkçe hata metin anahtarı döner. */
export function buildProfiles(rows: Profile[]): { profiles?: any[]; error?: string } {
  const names = new Set<string>()
  const out: any[] = []
  for (const r of rows) {
    const name = r.name.trim()
    if (!name) return { error: 'vi_bp_err_name' }
    if (names.has(name)) return { error: 'vi_bp_err_dup' }
    names.add(name)
    const vcpu = Number(r.vcpu), mem = Number(r.memory_gb), disk = Number(r.disk_gb || 0), count = Number(r.count || 1)
    if (!(vcpu >= 1) || !(mem >= 0) || !(disk >= 0) || !(count >= 1)) return { error: 'vi_bp_err_num' }
    const p: any = { name, vcpu, memory_gb: mem, disk_gb: disk, count }
    if (r.group.trim()) p.group = r.group.trim()
    out.push(p)
  }
  return out.length ? { profiles: out } : { error: 'vi_bp_err_empty' }
}

function ClusterPlan({ r }: { r: any }) {
  const t = useT()
  const head = r.fits ? (r.status === 'warn' ? 'vi_bp_warn_placed' : 'vi_bp_placed') : 'vi_bp_partial'
  return (
    <div className="rounded-lg border border-white/[0.06] p-3 space-y-2" data-testid="bp-cluster">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-sm text-white">{r.path || r.cluster}</span>
        <span className={`text-sm font-semibold ${TONE[r.status] || ''}`} data-testid={`bp-status-${r.status}`}>
          {t(head as any, { n: r.placed, total: r.requested })}
        </span>
        <GhostButton onClick={() => download(`yerlesim-${safeName(r.cluster)}.csv`, planToCsv([r]))}>
          <Download size={12} className="inline mr-1" />{t('vi_bp_csv')}
        </GhostButton>
      </div>
      {((r.limiting || []).length > 0 || (r.warn_codes || []).length > 0) && (
        <div className="flex flex-wrap gap-1">
          {(r.limiting || []).map((c: string) => <LimitChip key={`l-${c}`} code={c} tone="fail" />)}
          {(r.warn_codes || []).map((c: string) => <LimitChip key={`w-${c}`} code={c} tone="warn" />)}
        </div>
      )}
      <div className="text-xs text-slate-400 font-mono">
        {t('vi_bp_after')}: Memory %{fmt(r.before?.memory_effective_pct)} → %{fmt(r.after?.memory_effective_pct)}
        {' · '}vCPU:core {fmt(r.before?.vcpu_ratio, 2)} → {fmt(r.after?.vcpu_ratio, 2)}
      </div>
      {(r.unplaced || []).length > 0 && (
        <div className="rounded border border-red-500/30 bg-red-500/5 p-2 text-xs space-y-0.5" data-testid="bp-unplaced">
          <div className="text-red-300 font-medium">{t('vi_bp_unplaced')} ({r.unplaced.length})</div>
          {r.unplaced.map((u: any) => (
            <div key={u.vm} className="font-mono text-slate-300">
              {u.vm}{u.group ? ` [${u.group}]` : ''} · {fmt(u.memory_gb)} GB · <span className="text-red-300">{t(`vi_lim_${u.reason}` as any)}</span>
            </div>
          ))}
        </div>
      )}
      {(r.plan || []).length > 0 && (
        <details className="text-xs" open>
          <summary className="cursor-pointer text-slate-400">{t('vi_bp_plan')}</summary>
          <table className="w-full mt-1" data-testid="bp-plan">
            <thead><tr className="text-left text-slate-500">
              <th className="py-1">{t('vi_bp_col_vm')}</th><th>{t('vi_bp_col_profile')}</th><th>{t('vi_bp_col_group')}</th>
              <th>vCPU</th><th>Memory (GB)</th><th>{t('vi_bp_col_host')}</th><th>{t('vi_bp_col_ds')}</th>
            </tr></thead>
            <tbody>
              {r.plan.map((p: any) => (
                <tr key={p.vm} className="border-t border-white/[0.05] font-mono" data-testid="bp-plan-row">
                  <td className="py-1 text-slate-200">{p.vm}</td><td>{p.profile}</td><td>{p.group || '—'}</td>
                  <td>{p.vcpu}</td><td>{fmt(p.memory_gb)}</td><td className="text-slate-200">{p.host}</td><td>{p.datastore || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      {(r.by_host || []).length > 0 && (
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer">{t('vi_bp_hosts')}</summary>
          <div className="mt-1 font-mono space-y-0.5">
            {r.by_host.map((h: any) => <div key={h.host}>{t('vi_bp_host_line', { host: h.host, n: h.vms, mem: fmt(h.memory_gb), free: fmt(h.free_after_gb) })}</div>)}
          </div>
        </details>
      )}
      <ul className="list-disc pl-5 text-[11px] text-slate-500">{(r.notes || []).map((n: string) => <li key={n}>{n}</li>)}</ul>
    </div>
  )
}

export function BulkResults({ res }: { res: any }) {
  const t = useT()
  const results: any[] = res.results || []
  return (
    <div className="space-y-3" data-testid="bp-result">
      {results.length > 1 && (
        <GhostButton onClick={() => download('yerlesim-tum-clusterlar.csv', planToCsv(results))}>
          <Download size={12} className="inline mr-1" />{t('vi_bp_csv_all')}
        </GhostButton>
      )}
      {results.length === 0 && <div className="text-slate-500 text-sm">{t('vi_no_rows')}</div>}
      {results.map(r => <ClusterPlan key={`${r.hypervisor_id}:${r.cluster}`} r={r} />)}
      <ul className="list-disc pl-5 text-[11px] text-slate-500">{(res.assumptions || []).map((a: string) => <li key={a}>{a}</li>)}</ul>
    </div>
  )
}

let seq = 1
const blank = (): Profile => ({ id: seq++, name: '', vcpu: '4', memory_gb: '16', disk_gb: '100', count: '1', group: '' })

/** Toplu talep yerleşimi. Kapsam seçimi (instance/DC/cluster/host/platform) üst bileşenden gelir: `scopeNode` + `scopeBody`. */
export default function BulkPlacement({ scopeNode, scopeBody }: { scopeNode?: React.ReactNode; scopeBody?: () => Record<string, unknown> }) {
  const t = useT()
  const [rows, setRows] = useState<Profile[]>(() => [{ ...blank(), name: 'web', count: '2', group: 'web-ha' }])
  const [res, setRes] = useState<any>(null)
  const [err, setErr] = useState('')
  const set = (id: number, k: keyof Profile, v: string) => setRows(rs => rs.map(r => (r.id === id ? { ...r, [k]: v } : r)))
  const inp = 'rounded bg-black/30 border border-white/[0.08] px-2 py-1.5 text-sm text-white font-mono'
  const run = async () => {
    setErr('')
    const b = buildProfiles(rows)
    if (b.error) { setErr(t(b.error as any)); return }
    try {
      setRes(await apiSend('virt-insights', '/capacity/bulk-placement', 'POST', { profiles: b.profiles, ...(scopeBody ? scopeBody() : {}) }))
    } catch (e: any) { setErr(e.message) }
  }
  return (
    <div className="p-4 space-y-4" data-testid="bulk-placement">
      <div className="text-xs text-slate-400">{t('vi_bp_intro')}</div>
      {scopeNode}
      <div className="space-y-2">
        {rows.map(r => (
          <div key={r.id} className="flex flex-wrap items-end gap-2" data-testid="bp-profile">
            <label className="flex flex-col gap-1 text-xs text-slate-400">{t('vi_bp_name')}
              <input data-testid="bp-name" className={`${inp} w-36`} value={r.name} onChange={e => set(r.id, 'name', e.target.value)} /></label>
            <label className="flex flex-col gap-1 text-xs text-slate-400"><span className="inline-flex items-center">vCPU<TermHint k="vcpu" /></span>
              <input data-testid="bp-vcpu" type="number" className={`${inp} w-20`} value={r.vcpu} onChange={e => set(r.id, 'vcpu', e.target.value)} /></label>
            <label className="flex flex-col gap-1 text-xs text-slate-400"><span className="inline-flex items-center">Memory (GB)<TermHint k="memory" /></span>
              <input data-testid="bp-mem" type="number" className={`${inp} w-24`} value={r.memory_gb} onChange={e => set(r.id, 'memory_gb', e.target.value)} /></label>
            <label className="flex flex-col gap-1 text-xs text-slate-400"><span className="inline-flex items-center">Disk (GB)<TermHint k="disk" /></span>
              <input data-testid="bp-disk" type="number" className={`${inp} w-24`} value={r.disk_gb} onChange={e => set(r.id, 'disk_gb', e.target.value)} /></label>
            <label className="flex flex-col gap-1 text-xs text-slate-400"><span className="inline-flex items-center">{t('vi_whatif_count')}<TermHint k="count" /></span>
              <input data-testid="bp-count" type="number" className={`${inp} w-20`} value={r.count} onChange={e => set(r.id, 'count', e.target.value)} /></label>
            <label className="flex flex-col gap-1 text-xs text-slate-400"><span className="inline-flex items-center">{t('vi_bp_group')}<TermHint k="group" /></span>
              <input data-testid="bp-group" className={`${inp} w-36`} placeholder={t('vi_bp_group_ph')} value={r.group} onChange={e => set(r.id, 'group', e.target.value)} /></label>
            <button type="button" aria-label={t('vi_bp_remove')} title={t('vi_bp_remove')} disabled={rows.length < 2} data-testid="bp-remove"
              onClick={() => setRows(rs => rs.filter(x => x.id !== r.id))}
              className="pb-2 text-slate-500 hover:text-red-300 disabled:opacity-30"><Trash2 size={14} /></button>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <GhostButton onClick={() => { if (rows.length < MAX_ROWS) setRows(rs => [...rs, blank()]) }}><Plus size={12} className="inline mr-1" />{t('vi_bp_add')}</GhostButton>
        <GhostButton accent={NEON.blue} onClick={run}>{t('vi_bp_run')}</GhostButton>
      </div>
      {err && <div className="text-red-300 text-xs" data-testid="bp-error">{err}</div>}
      {res && <BulkResults res={res} />}
    </div>
  )
}
